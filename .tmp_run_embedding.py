from src import embedding
import sys
sys.argv = ["embedding.py", "--input", "data/chunks_postgres.jsonl", "--output", "data/chunks_embeddings.jsonl", "--batch-size", "16"]
embedding.main()
print('embedding_main_completed')
