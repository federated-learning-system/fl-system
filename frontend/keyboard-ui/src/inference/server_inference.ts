/**
 * Fallback server-side inference via the Inference Server REST API.
 * Used when ONNX Runtime Web session hasn't loaded yet.
 */

const API_BASE = "/api";

export async function fetchServerSuggestions(
  tokenIds: number[],
  topK: number = 3,
): Promise<string[]> {
  const resp = await fetch(`${API_BASE}/infer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      token_ids: tokenIds.slice(-10), // last 10 tokens
      top_k: topK,
    }),
  });

  if (!resp.ok) {
    throw new Error(`Inference server error: ${resp.status}`);
  }

  const data = await resp.json();
  // Server returns { suggestions: ["word1", "word2", "word3"] }
  return data.suggestions ?? [];
}
