from src import qdrant_loader
import sys
sys.argv = ["qdrant_loader.py", "--input", "data/chunks_embeddings.jsonl"]
qdrant_loader.main()
print('qdrant_main_completed')
