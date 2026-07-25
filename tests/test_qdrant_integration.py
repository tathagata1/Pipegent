import os
import unittest
import uuid

from memory.vector_store import QdrantVectorStore, VectorRecord


@unittest.skipUnless(
    os.getenv("RUN_QDRANT_INTEGRATION") == "1",
    "set RUN_QDRANT_INTEGRATION=1 with local Qdrant running",
)
class QdrantIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.collection = "pipegent_test_" + uuid.uuid4().hex
        self.store = QdrantVectorStore(
            os.getenv("QDRANT_URL", "http://localhost:6333"),
            self.collection, 4, os.getenv("QDRANT_API_KEY", ""),
        )
        self.store.initialise()

    def tearDown(self):
        self.store.client.delete_collection(self.collection)

    def test_collection_upsert_filter_update_delete_and_reconnect(self):
        point_id = str(uuid.uuid4())
        self.store.upsert([VectorRecord(
            point_id, [1, 0, 0, 0],
            {"tenant_id": "one", "user_id": "alice", "status": "active"},
        )])
        self.store.upsert([VectorRecord(
            point_id, [0.9, 0.1, 0, 0],
            {"tenant_id": "one", "user_id": "alice", "status": "active"},
        )])
        self.store.upsert([VectorRecord(
            str(uuid.uuid4()), [1, 0, 0, 0],
            {"tenant_id": "two", "user_id": "alice", "status": "active"},
        )])
        results = self.store.search(
            [1, 0, 0, 0], top_k=10,
            filters={"tenant_id": "one", "user_id": "alice", "status": "active"},
        )
        self.assertEqual([item.id for item in results], [point_id])
        reconnected = QdrantVectorStore(
            self.store.url, self.collection, 4, self.store.api_key
        )
        self.assertTrue(reconnected.search(
            [1, 0, 0, 0], top_k=1,
            filters={"tenant_id": "one", "user_id": "alice", "status": "active"},
        ))
        reconnected.delete([point_id])
        self.assertFalse(reconnected.search(
            [1, 0, 0, 0], top_k=1,
            filters={"tenant_id": "one", "user_id": "alice", "status": "active"},
        ))
