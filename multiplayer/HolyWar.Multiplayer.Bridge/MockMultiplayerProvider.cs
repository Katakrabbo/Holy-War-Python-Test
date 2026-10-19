using System.Text.Json;

namespace HolyWar.Multiplayer.Bridge;

internal sealed class MockMultiplayerProvider : IMultiplayerProvider
{
    private bool _initialized;
    private string? _userId;
    private string? _lobbyId;

    public event Func<string, object, Task>? EventRaised;

    public async Task<object?> ExecuteAsync(
        string operation,
        JsonElement payload,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        switch (operation.Trim().ToLowerInvariant())
        {
            case "initialize":
                _initialized = true;
                return new { provider = "mock", initialized = true };
            case "status":
                return new { provider = "mock", initialized = _initialized, userId = _userId, lobbyId = _lobbyId };
            case "login":
                EnsureInitialized();
                _userId = ReadOptionalString(payload, "displayName") ?? $"mock-{Guid.NewGuid():N}";
                return new { userId = _userId };
            case "create_lobby":
                EnsureLoggedIn();
                _lobbyId = $"mock-{Guid.NewGuid():N}";
                return new { lobbyId = _lobbyId, ownerId = _userId, maxMembers = 2 };
            case "join_lobby":
                EnsureLoggedIn();
                _lobbyId = ReadRequiredString(payload, "lobbyId");
                return new { lobbyId = _lobbyId, ownerId = "mock-host", maxMembers = 2 };
            case "leave_lobby":
                _lobbyId = null;
                return new { left = true };
            case "send_packet":
                EnsureInLobby();
                var data = ReadRequiredString(payload, "data");
                if (EventRaised is not null)
                {
                    await EventRaised("packet_received", new { senderId = _userId, data });
                }
                return new { sent = true, bytes = System.Text.Encoding.UTF8.GetByteCount(data) };
            default:
                throw new InvalidOperationException($"Operazione bridge sconosciuta: {operation}");
        }
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;

    private void EnsureInitialized()
    {
        if (!_initialized) throw new InvalidOperationException("Bridge non inizializzato.");
    }

    private void EnsureLoggedIn()
    {
        EnsureInitialized();
        if (string.IsNullOrWhiteSpace(_userId)) throw new InvalidOperationException("Login richiesto.");
    }

    private void EnsureInLobby()
    {
        EnsureLoggedIn();
        if (string.IsNullOrWhiteSpace(_lobbyId)) throw new InvalidOperationException("Lobby richiesta.");
    }

    private static string ReadRequiredString(JsonElement payload, string name) =>
        ReadOptionalString(payload, name) ?? throw new InvalidOperationException($"Campo richiesto mancante: {name}");

    private static string? ReadOptionalString(JsonElement payload, string name)
    {
        if (payload.ValueKind != JsonValueKind.Object || !payload.TryGetProperty(name, out var value)) return null;
        var result = value.GetString()?.Trim();
        return string.IsNullOrEmpty(result) ? null : result;
    }
}
