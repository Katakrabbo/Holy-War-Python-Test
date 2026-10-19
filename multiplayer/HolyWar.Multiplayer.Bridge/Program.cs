using System.Text.Json;
using HolyWar.Multiplayer.Bridge;

if (args.Contains("--self-test", StringComparer.OrdinalIgnoreCase))
{
    await RunSelfTestAsync();
    return;
}

var providerName = ReadArgument(args, "--provider")
    ?? Environment.GetEnvironmentVariable("HOLYWAR_MULTIPLAYER_PROVIDER")
    ?? "mock";
var settingsPath = ReadArgument(args, "--settings")
    ?? Environment.GetEnvironmentVariable("HOLYWAR_EOS_SETTINGS");

await using IMultiplayerProvider provider = providerName.Trim().ToLowerInvariant() switch
{
    "mock" => new MockMultiplayerProvider(),
#if EOS_SDK_AVAILABLE
    "eos" => new EosMultiplayerProvider(settingsPath),
#else
    "eos" => throw new InvalidOperationException(
        "Provider EOS non disponibile: estrai l'SDK C# in multiplayer/eos-sdk."),
#endif
    _ => throw new InvalidOperationException($"Provider multiplayer non supportato: {providerName}"),
};
var outputLock = new SemaphoreSlim(1, 1);

async Task WriteAsync(BridgeResponse message)
{
    var json = JsonSerializer.Serialize(message, BridgeProtocol.JsonOptions);
    await outputLock.WaitAsync();
    try
    {
        await Console.Out.WriteLineAsync(json);
        await Console.Out.FlushAsync();
    }
    finally
    {
        outputLock.Release();
    }
}

provider.EventRaised += (eventName, payload) => WriteAsync(
    new BridgeResponse(BridgeProtocol.Version, eventName, null, true, payload));

while (await Console.In.ReadLineAsync() is { } line)
{
    if (string.IsNullOrWhiteSpace(line)) continue;
    BridgeCommand? command = null;
    try
    {
        command = JsonSerializer.Deserialize<BridgeCommand>(line, BridgeProtocol.JsonOptions)
            ?? throw new InvalidOperationException("Comando JSON vuoto.");
        if (command.ProtocolVersion != BridgeProtocol.Version)
        {
            throw new InvalidOperationException(
                $"Versione protocollo {command.ProtocolVersion} non supportata; attesa {BridgeProtocol.Version}.");
        }
        if (string.IsNullOrWhiteSpace(command.RequestId)) throw new InvalidOperationException("requestId richiesto.");
        if (command.Operation.Equals("shutdown", StringComparison.OrdinalIgnoreCase))
        {
            await WriteAsync(new BridgeResponse(BridgeProtocol.Version, "response", command.RequestId, true));
            break;
        }
        var result = await provider.ExecuteAsync(command.Operation, command.Payload, CancellationToken.None);
        await WriteAsync(new BridgeResponse(BridgeProtocol.Version, "response", command.RequestId, true, result));
    }
    catch (Exception exception)
    {
        await WriteAsync(new BridgeResponse(
            BridgeProtocol.Version,
            "response",
            command?.RequestId,
            false,
            Error: exception.Message));
    }
}

static async Task RunSelfTestAsync()
{
    await using var provider = new MockMultiplayerProvider();
    using var empty = JsonDocument.Parse("{}");
    await provider.ExecuteAsync("initialize", empty.RootElement, CancellationToken.None);
    using var login = JsonDocument.Parse("{\"displayName\":\"tester\"}");
    await provider.ExecuteAsync("login", login.RootElement, CancellationToken.None);
    var lobby = await provider.ExecuteAsync("create_lobby", empty.RootElement, CancellationToken.None);
    if (lobby is null) throw new InvalidOperationException("Self-test lobby fallito.");
}

static string? ReadArgument(string[] arguments, string name)
{
    for (var index = 0; index < arguments.Length - 1; index++)
    {
        if (arguments[index].Equals(name, StringComparison.OrdinalIgnoreCase))
        {
            return arguments[index + 1];
        }
    }

    return null;
}
