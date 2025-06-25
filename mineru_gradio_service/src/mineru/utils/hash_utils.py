import hashlib

def str_sha256(input_string: str) -> str:
    """
    Computes the SHA256 hash of a string.
    """
    if not isinstance(input_string, str):
        raise TypeError("Input must be a string.")
    return hashlib.sha256(input_string.encode('utf-8')).hexdigest()
