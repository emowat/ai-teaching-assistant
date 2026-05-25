import json
import numpy as np
from sentence_transformers import SentenceTransformer

def rebuild():
    print("Loading SentenceTransformer model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    
    embeddings = []
    
    print("Reading synthetic_c_plus_plus_dataset.jsonl...")
    try:
        with open("synthetic_c_plus_plus_dataset.jsonl", "r") as f:
            for line in f:
                if not line.strip(): continue
                entry = json.loads(line)
                
                # Reconstruct the exact semantic fingerprint used in generate_dataset.py
                code = entry.get("code", "")
                initial_message = entry.get("initial_message", "")
                problem_text = code + "\n" + initial_message
                
                emb = model.encode(problem_text)
                embeddings.append(emb)
                
        np.save("embeddings.npy", np.array(embeddings))
        print(f"Successfully rebuilt embeddings.npy with {len(embeddings)} entries!")
        
    except FileNotFoundError:
        print("Error: synthetic_c_plus_plus_dataset.jsonl not found.")

if __name__ == "__main__":
    rebuild()
