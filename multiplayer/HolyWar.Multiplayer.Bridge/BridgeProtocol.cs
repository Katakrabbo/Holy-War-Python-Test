using System.Text.Json;
using System.Text.Json.Serialization;

namespace HolyWar.Multiplayer.Bridge;

internal static class BridgeProtocol
{
    public const int Version = 1;
    public static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}

internal sealed record BridgeCommand(
    int ProtocolVersion,
    string RequestId,
    string Operation,
    JsonElement Payload);

internal sealed record BridgeResponse(
    int ProtocolVersion,
    string Type,
    string? RequestId,
    bool Ok,
    object? Payload = null,
    string? Error = null);
