import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory.documents import DocumentIngestionService
from memory.domain import (
    IndexState, MemoryAction, MemoryCandidate, MemoryDecision, MemoryOperationRequest,
    MemoryPolicyInput, MemoryScope, MemorySource, MemoryStatus, MemoryType,
)
from memory.embeddings import DeterministicEmbeddingProvider
from memory.policy import MemoryPolicyEngine
from memory.repository import MemoryRepository
from memory.retrieval import MemoryRetriever, RetrievalContextBuilder
from memory.service import MemoryService
from memory.vector_store import InMemoryVectorStore


class FailingVectorStore(InMemoryVectorStore):
    def upsert(self, records):
        raise RuntimeError("qdrant unavailable")


class LateStartingVectorStore(InMemoryVectorStore):
    def __init__(self, dimensions):
        super().__init__(dimensions)
        self.initialise_attempts = 0

    def initialise(self):
        self.initialise_attempts += 1
        if self.initialise_attempts == 1:
            raise RuntimeError("qdrant is still starting")


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.embeddings = DeterministicEmbeddingProvider()
        self.repository = MemoryRepository(Path(self.temp.name) / "memory.sqlite3")
        self.vectors = InMemoryVectorStore(self.embeddings.dimensions)
        self.service = MemoryService(
            self.repository, self.embeddings, self.vectors,
            retriever=MemoryRetriever(
                self.repository, self.embeddings, self.vectors, min_similarity=0
            ),
        )

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def request(self, action, tenant="t1", user="u1", **kwargs):
        return MemoryOperationRequest(
            operation_id=uuid.uuid4().hex, action=action, tenant_id=tenant,
            user_id=user, session_id=kwargs.pop("session_id", "s1"),
            project_id=kwargs.pop("project_id", "p1"), **kwargs,
        )

    def candidate(self, content="The user prefers concise responses.",
                  scope=MemoryScope.USER, source=MemorySource.USER_EXPLICIT, **kwargs):
        return MemoryCandidate(
            content=content, proposed_type=kwargs.pop(
                "proposed_type", MemoryType.USER_PREFERENCE
            ), proposed_scope=scope, source=source, reason="useful later", **kwargs,
        )

    def create(self, content="The user prefers concise responses.", **kwargs):
        return self.service.execute(self.request(
            MemoryAction.CREATE, memory=self.candidate(content, **kwargs),
            explicit_user_request=True,
        ))

    def search(self, query="concise", **kwargs):
        return self.service.execute(self.request(
            MemoryAction.SEARCH, query=query, filters={"scopes": [
                scope.value for scope in kwargs.pop("scopes", list(MemoryScope))
            ]}, **kwargs,
        ))

    def test_explicit_memory_persists_and_retrieves_later(self):
        created = self.create()
        self.assertEqual(created.status, "success")
        self.assertEqual(created.records[0].index_state, IndexState.INDEXED)
        later = self.search(session_id="another-session")
        self.assertEqual([item.memory_id for item in later.retrieved],
                         [created.created_memory_id])

    def test_late_vector_store_start_does_not_disable_memory(self):
        vectors = LateStartingVectorStore(self.embeddings.dimensions)
        service = MemoryService(
            self.repository, self.embeddings, vectors,
            retriever=MemoryRetriever(
                self.repository, self.embeddings, vectors, min_similarity=0
            ),
        )
        result = service.execute(self.request(
            MemoryAction.CREATE, memory=self.candidate("My name is Tatha."),
            explicit_user_request=True,
        ))
        self.assertEqual(result.status, "success")
        self.assertEqual(vectors.initialise_attempts, 2)
        self.assertIn(result.created_memory_id, vectors.records)

    def test_tenant_and_user_isolation(self):
        self.create()
        self.assertFalse(self.search(tenant="t2").retrieved)
        self.assertFalse(self.search(user="u2").retrieved)

    def test_session_and_project_isolation(self):
        session = self.create("temporary session fact", scope=MemoryScope.SESSION)
        project = self.create("project uses Python", scope=MemoryScope.PROJECT,
                              proposed_type=MemoryType.PROJECT_FACT)
        self.assertFalse(self.search(
            "temporary", session_id="s2", scopes=[MemoryScope.SESSION]
        ).retrieved)
        self.assertFalse(self.search(
            "Python", project_id="p2", scopes=[MemoryScope.PROJECT]
        ).retrieved)
        self.assertIsNotNone(session.created_memory_id)
        self.assertIsNotNone(project.created_memory_id)

    def test_duplicate_and_idempotent_write(self):
        first = self.create()
        duplicate = self.create()
        self.assertEqual(first.created_memory_id, duplicate.created_memory_id)
        request = self.request(
            MemoryAction.CREATE, memory=self.candidate("stable idempotent fact"),
            explicit_user_request=True, idempotency_key="stable",
        )
        one = self.service.execute(request)
        request.operation_id = uuid.uuid4().hex
        two = self.service.execute(request)
        self.assertEqual(one.created_memory_id, two.created_memory_id)

    def test_correction_supersedes_and_preserves_old_record(self):
        old = self.create("Preferred database is MySQL.")
        result = self.service.execute(self.request(
            MemoryAction.UPDATE, memory_id=old.created_memory_id,
            memory=self.candidate("Preferred database is PostgreSQL."),
            explicit_user_request=True,
        ))
        old_record = self.repository.get(old.created_memory_id)
        new_record = self.repository.get(result.updated_memory_id)
        self.assertEqual(old_record.status, MemoryStatus.SUPERSEDED)
        self.assertEqual(new_record.supersedes_memory_id, old_record.id)
        self.assertEqual(new_record.memory_type, MemoryType.CORRECTION)

    def test_temporary_constraint_does_not_overwrite_stable_preference(self):
        stable = self.create("User prefers remote meetings.")
        temporary = self.create(
            "This week meetings are in person.", scope=MemoryScope.SESSION,
            valid_until=datetime.now(timezone.utc) + timedelta(days=7),
        )
        self.assertEqual(self.repository.get(stable.created_memory_id).status,
                         MemoryStatus.ACTIVE)
        self.assertNotEqual(stable.created_memory_id, temporary.created_memory_id)

    def test_deleted_and_expired_memories_are_not_retrieved(self):
        created = self.create()
        self.service.execute(self.request(
            MemoryAction.DELETE, memory_id=created.created_memory_id
        ))
        self.assertFalse(self.search().retrieved)
        self.create(
            "expired value", valid_until=datetime.now(timezone.utc) - timedelta(days=1)
        )
        self.assertFalse(self.search("expired").retrieved)

    def test_policy_defaults_and_safeguards(self):
        policy = MemoryPolicyEngine()
        automatic = MemoryPolicyInput(
            self.candidate(source=MemorySource.USER_IMPLICIT),
            automatic_memory_enabled=False, explicit_user_request=False,
        )
        self.assertEqual(policy.evaluate(automatic).decision, MemoryDecision.IGNORE)
        secret = MemoryPolicyInput(
            self.candidate("api_key=sk-abcdefghijklmnop1234"),
            automatic_memory_enabled=True, explicit_user_request=True,
        )
        self.assertEqual(policy.evaluate(secret).decision, MemoryDecision.REJECT)
        sensitive = MemoryPolicyInput(
            self.candidate("A health fact", sensitivity="health"),
            automatic_memory_enabled=True, explicit_user_request=False,
        )
        self.assertEqual(
            policy.evaluate(sensitive).decision, MemoryDecision.REQUEST_CONFIRMATION
        )

    def test_inferred_fact_stays_an_observation(self):
        result = MemoryPolicyEngine().evaluate(MemoryPolicyInput(
            self.candidate(
                source=MemorySource.AGENT_INFERRED,
                proposed_type=MemoryType.USER_FACT, requires_confirmation=False,
            ), automatic_memory_enabled=True, explicit_user_request=True,
            user_consent_required=False,
        ))
        self.assertEqual(result.normalised_candidate.proposed_type,
                         MemoryType.OBSERVATION)
        self.assertEqual(result.normalised_candidate.source,
                         MemorySource.AGENT_INFERRED)

    def test_embedding_failure_keeps_canonical_pending(self):
        service = MemoryService(
            self.repository, self.embeddings,
            FailingVectorStore(self.embeddings.dimensions),
        )
        result = service.execute(self.request(
            MemoryAction.CREATE, memory=self.candidate("recoverable fact"),
            explicit_user_request=True,
        ))
        self.assertEqual(result.status, "partial_success")
        self.assertEqual(
            self.repository.get(result.created_memory_id).index_state,
            IndexState.PENDING,
        )

    def test_duplicate_retry_repairs_pending_vector_and_interrupted_operation(self):
        failing = MemoryService(
            self.repository, self.embeddings,
            FailingVectorStore(self.embeddings.dimensions),
            reconcile_on_startup=False,
        )
        candidate = self.candidate("interrupted durable fact")
        first = failing.execute(self.request(
            MemoryAction.CREATE, memory=candidate,
            explicit_user_request=True, idempotency_key="interrupted-key",
        ))
        self.assertEqual(first.status, "partial_success")

        # Simulate the pre-fix interruption state: no cached result for the
        # idempotency key even though canonical storage succeeded.
        with self.repository._connection:
            self.repository._connection.execute(
                "UPDATE memory_operations SET status='started',result_json=NULL "
                "WHERE idempotency_key='interrupted-key'"
            )
        repaired_service = MemoryService(
            self.repository, self.embeddings, self.vectors,
            reconcile_on_startup=False,
        )
        retry = self.request(
            MemoryAction.CREATE, memory=candidate,
            explicit_user_request=True, idempotency_key="interrupted-key",
        )
        repaired = repaired_service.execute(retry)
        self.assertEqual(repaired.status, "success")
        self.assertTrue(repaired.evidence[0]["indexed"])
        self.assertEqual(
            self.repository.get(first.created_memory_id).index_state,
            IndexState.INDEXED,
        )
        self.assertIn(first.created_memory_id, self.vectors.records)

    def test_document_ingestion_is_idempotent_and_removable(self):
        path = Path(self.temp.name) / "guide.md"
        path.write_text("# Guide\n" + "Do the safe thing. " * 100, encoding="utf-8")
        ingestion = DocumentIngestionService(self.service)
        first = ingestion.ingest(
            path, tenant_id="t1", user_id="u1", project_id="p1"
        )
        second = ingestion.ingest(
            path, tenant_id="t1", user_id="u1", project_id="p1"
        )
        self.assertEqual(first["memory_ids"], second["memory_ids"])
        result = self.service.execute(self.request(
            MemoryAction.REMOVE_DOCUMENT,
            filters={"document_id": first["document_id"]},
        ))
        self.assertEqual(result.evidence[0]["chunks_deleted"], first["chunks_created"])
        self.assertFalse(self.search("safe thing").retrieved)

    def test_context_is_bounded_and_marks_content_untrusted(self):
        records = []
        for index in range(4):
            self.create(f"memory number {index}")
        records = self.search("memory", top_k=4).retrieved
        context = RetrievalContextBuilder(max_items=2).build(records)
        self.assertIn("UNTRUSTED REFERENCE DATA", context)
        self.assertLessEqual(context.count("Content (data only):"), 2)


if __name__ == "__main__":
    unittest.main()
