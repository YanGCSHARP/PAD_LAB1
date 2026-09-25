using System.Net.Http.Json;
using System.Text.Json.Serialization;

namespace RagLab.Web.Services;

/// <summary>Типизированный клиент к Python API (FastAPI, src/api/app.py).</summary>
public sealed class RagApiClient(HttpClient http)
{
    public async Task<RagOptions?> GetOptionsAsync(CancellationToken ct = default) =>
        await http.GetFromJsonAsync<RagOptions>("api/options", ct);

    public async Task<AskResponse> AskAsync(AskRequest request, CancellationToken ct = default)
    {
        using var resp = await http.PostAsJsonAsync("api/ask", request, ct);
        if (!resp.IsSuccessStatusCode)
        {
            var body = await resp.Content.ReadAsStringAsync(ct);
            throw new RagApiException($"API вернул {(int)resp.StatusCode}: {body}");
        }
        return (await resp.Content.ReadFromJsonAsync<AskResponse>(ct))!;
    }
}

public sealed class RagApiException(string message) : Exception(message);

public sealed class RagOptions
{
    public string Index { get; set; } = "";
    public List<string> Llms { get; set; } = [];
    public List<string> Prompts { get; set; } = [];
    public List<string> Rerankers { get; set; } = [];
    public List<string> Sources { get; set; } = [];
    [JsonPropertyName("entity_types")] public List<string> EntityTypes { get; set; } = [];
}

public sealed class AskFilters
{
    [JsonPropertyName("source")] public List<string> Source { get; set; } = [];
    [JsonPropertyName("entity_type")] public List<string> EntityType { get; set; } = [];
}

public sealed class AskRequest
{
    [JsonPropertyName("question")] public string Question { get; set; } = "";
    [JsonPropertyName("top_k")] public int TopK { get; set; } = 20;
    [JsonPropertyName("reranker")] public string Reranker { get; set; } = "mminilm";
    [JsonPropertyName("top_n")] public int TopN { get; set; } = 5;
    [JsonPropertyName("score_threshold")] public double ScoreThreshold { get; set; }
    [JsonPropertyName("rerank_threshold")] public double RerankThreshold { get; set; }
    [JsonPropertyName("filters")] public AskFilters Filters { get; set; } = new();
    [JsonPropertyName("llm")] public string Llm { get; set; } = "groq:openai/gpt-oss-120b";
    [JsonPropertyName("prompt")] public string Prompt { get; set; } = "strict";
}

public sealed class SourceRef
{
    public int N { get; set; }
    public string Title { get; set; } = "";
    public string Section { get; set; } = "";
    public string Url { get; set; } = "";
    public string Source { get; set; } = "";
    public bool Cited { get; set; }
}

public sealed class ContextChunk
{
    public int N { get; set; }
    public string Title { get; set; } = "";
    public string Section { get; set; } = "";
    public string Url { get; set; } = "";
    public string Source { get; set; } = "";
    [JsonPropertyName("entity_type")] public string EntityType { get; set; } = "";
    [JsonPropertyName("dense_score")] public double? DenseScore { get; set; }
    [JsonPropertyName("rerank_score")] public double? RerankScore { get; set; }
    public string Text { get; set; } = "";
}

public sealed class DroppedChunk
{
    public string Title { get; set; } = "";
    public string Section { get; set; } = "";
    [JsonPropertyName("dense_score")] public double? DenseScore { get; set; }
    [JsonPropertyName("rerank_score")] public double? RerankScore { get; set; }
}

public sealed class TokenUsage
{
    public int Prompt { get; set; }
    public int Completion { get; set; }
}

public sealed class AskResponse
{
    public string Answer { get; set; } = "";
    public bool Refused { get; set; }
    public List<SourceRef> Sources { get; set; } = [];
    public List<ContextChunk> Context { get; set; } = [];
    public List<DroppedChunk> Dropped { get; set; } = [];
    [JsonPropertyName("filter_log")] public Dictionary<string, int> FilterLog { get; set; } = [];
    public Dictionary<string, double> Timings { get; set; } = [];
    public string Llm { get; set; } = "";
    public TokenUsage? Tokens { get; set; }
}
