import configparser

config = configparser.ConfigParser()
config.read('config.ini')

rapidapi_url=config['API']['rapidapi_url']
rapidapi_key=config['API']['rapidapi_key']
rapidapi_service=config['API']['rapidapi_service']
chatgpt_key=config['API']['chatgpt_key']