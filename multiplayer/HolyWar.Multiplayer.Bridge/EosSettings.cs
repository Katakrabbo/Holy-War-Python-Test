using System.Text.Json;

namespace HolyWar.Multiplayer.Bridge;

internal sealed class EosSettings
{
    public string ProductId { get; init; } = "";
    public string SandboxId { get; init; } = "";
    public string DeploymentId { get; init; } = "";
    public string ClientId { get; init; } = "";
    public string ClientSecret { get; init; } = "";
    public string EncryptionKey { get; init; } = "";
    public string Environment { get; init; } = "Development";

    public static EosSettings Load(string? requestedPath)
    {
        var candidates = new[]
        {
            requestedPath,
            Path.Combine(AppContext.BaseDirectory, "eos.settings.json"),
            Path.Combine(Directory.GetCurrentDirectory(), "multiplayer", "eos.settings.json"),
            Path.Combine(Directory.GetCurrentDirectory(), "eos.settings.json"),
        };
        var path = candidates.FirstOrDefault(candidate =>
            !string.IsNullOrWhiteSpace(candidate) && File.Exists(Path.GetFullPath(candidate)));
        if (path is null)
        {
            throw new InvalidOperationException(
                "Configurazione EOS non trovata. Esegui scripts/configure_eos.ps1.");
        }

        var settings = JsonSerializer.Deserialize<EosSettings>(
            File.ReadAllText(path),
            BridgeProtocol.JsonOptions) ?? throw new InvalidOperationException("Configurazione EOS non valida.");
        var missing = new Dictionary<string, string>
        {
            ["productId"] = settings.ProductId,
            ["sandboxId"] = settings.SandboxId,
            ["deploymentId"] = settings.DeploymentId,
            ["clientId"] = settings.ClientId,
            ["clientSecret"] = settings.ClientSecret,
        }.Where(pair => string.IsNullOrWhiteSpace(pair.Value)).Select(pair => pair.Key).ToArray();
        if (missing.Length > 0)
        {
            throw new InvalidOperationException($"Campi EOS mancanti: {string.Join(", ", missing)}.");
        }

        return settings;
    }
}
