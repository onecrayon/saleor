from .fixtures import *


@pytest.fixture(scope='module')
def vcr_config():
    return {
        # Decompress the response body so it's human-readable
        'decode_compressed_response': True,
    }
