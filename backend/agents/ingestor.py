import os
import json
from pathlib import Path
from pypdf import PdfReader
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

CHROMA_PATH = "./data/chroma"
client = chromadb.PersistentClient(path=CHROMA_PATH)


class GeminiEmbeddingFunction(EmbeddingFunction):
    """Embedding function custom che usa Gemini text-embedding-004."""
    def __call__(self, texts: Documents) -> Embeddings:
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=texts,
            task_type="retrieval_document"
        )
        embeddings: list = result["embedding"]
        if embeddings and isinstance(embeddings[0], float):
            embeddings = [embeddings]
        return embeddings  # type: ignore[return-value]


gemini_ef = GeminiEmbeddingFunction()


def get_collection(student_id: int, exam_id: int) -> chromadb.Collection:
    """Ogni esame ha la sua collection isolata."""
    name = f"student_{student_id}_exam_{exam_id}"
    return client.get_or_create_collection(
        name=name,
        embedding_function=gemini_ef,
        metadata={"student_id": student_id, "exam_id": exam_id}
    )


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Divide il testo in chunk di chunk_size parole con overlap."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


def ingest_pdf(pdf_path: str, student_id: int, exam_id: int) -> dict:
    """
    Legge un PDF, lo divide in chunk, genera embedding e salva in ChromaDB.
    Ritorna un dizionario con le statistiche dell'indicizzazione.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF non trovato: {pdf_path}")

    reader = PdfReader(str(path))
    pages_text: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append((i + 1, text))

    if not pages_text:
        raise ValueError("Il PDF non contiene testo estraibile (potrebbe essere scansionato).")

    all_chunks: list[str] = []
    all_metadata: list[dict] = []
    all_ids: list[str] = []

    chunk_counter = 0
    for page_num, text in pages_text:
        for chunk in chunk_text(text):
            if len(chunk.strip()) < 20:
                continue
            all_chunks.append(chunk)
            all_metadata.append({
                "student_id": student_id,
                "exam_id": exam_id,
                "page": page_num,
                "source": path.name
            })
            all_ids.append(f"s{student_id}_e{exam_id}_c{chunk_counter}")
            chunk_counter += 1

    collection = get_collection(student_id, exam_id)
    batch_size = 100
    for i in range(0, len(all_chunks), batch_size):
        collection.add(
            documents=all_chunks[i:i + batch_size],
            metadatas=all_metadata[i:i + batch_size],
            ids=all_ids[i:i + batch_size]
        )

    stats = {
        "file": path.name,
        "pages": len(pages_text),
        "chunks": chunk_counter,
        "collection": f"student_{student_id}_exam_{exam_id}"
    }
    print(f"[Ingestor] {json.dumps(stats, indent=2)}")
    return stats


def retrieve_chunks(
    query: str,
    student_id: int,
    exam_id: int,
    n_results: int = 5
) -> list[str]:
    """
    Recupera i chunk più rilevanti per una query.
    Usato dal Quiz Generator e dal Socratic Tutor.
    """
    collection = get_collection(student_id, exam_id)
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    documents = results.get("documents")
    if not documents or not documents[0]:
        return []
    return documents[0]


def delete_exam_collection(student_id: int, exam_id: int) -> None:
    """
    Elimina tutti i chunk di un esame.
    Da chiamare se lo studente ricarica il materiale.
    """
    name = f"student_{student_id}_exam_{exam_id}"
    try:
        client.delete_collection(name)
        print(f"[Ingestor] Collection {name} eliminata.")
    except ValueError:
        pass