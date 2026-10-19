using System.Text.Json;

namespace HolyWar.Multiplayer.Bridge;

internal interface IMultiplayerProvider : IAsyncDisposable
{
    event Func<string, object, Task>? EventRaised;

    Task<object?> ExecuteAsync(string operation, JsonElement payload, CancellationToken cancellationToken);
}
