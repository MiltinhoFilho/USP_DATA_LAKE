try:
    import sentence_transformers
    print('sentence_transformers installed')
    from sentence_transformers import SentenceTransformer
    print('SentenceTransformer available')
except Exception as e:
    print(type(e).__name__, e)
