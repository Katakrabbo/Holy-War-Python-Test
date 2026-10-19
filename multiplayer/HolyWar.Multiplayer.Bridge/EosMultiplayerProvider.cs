using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using Epic.OnlineServices;
using Epic.OnlineServices.Connect;
using Epic.OnlineServices.Lobby;
using Epic.OnlineServices.Logging;
using Epic.OnlineServices.P2P;
using Epic.OnlineServices.Platform;
using ConnectCredentials = Epic.OnlineServices.Connect.Credentials;
using ConnectLoginOptions = Epic.OnlineServices.Connect.LoginOptions;
using PlatformOptions = Epic.OnlineServices.Platform.WindowsOptions;

namespace HolyWar.Multiplayer.Bridge;

internal sealed class EosMultiplayerProvider : IMultiplayerProvider
{
    private const string SocketName = "HOLYWAR_V1";
    private const string BucketId = "holywar-turnbased-v1";

    private readonly string? _settingsPath;
    private readonly ConcurrentDictionary<string, byte> _members = new(StringComparer.Ordinal);
    private readonly BlockingCollection<Action> _sdkActions = new();
    private readonly CancellationTokenSource _tickCancellation = new();
    private readonly Thread _sdkThread;
    private readonly SocketId _socketId = new() { SocketName = SocketName };

    private PlatformInterface? _platform;
    private ConnectInterface? _connect;
    private LobbyInterface? _lobby;
    private P2PInterface? _p2p;
    private ProductUserId? _localUserId;
    private string? _lobbyId;
    private string? _ownerId;
    private ulong _lobbyMemberNotificationId;
    private ulong _connectionRequestNotificationId;
    private bool _sdkInitialized;

    public EosMultiplayerProvider(string? settingsPath)
    {
        _settingsPath = settingsPath;
        _sdkThread = new Thread(RunSdkThread)
        {
            IsBackground = true,
            Name = "HolyWar EOS",
        };
        _sdkThread.Start();
    }

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
                return await InvokeOnSdkThreadAsync(Initialize, cancellationToken);
            case "status":
                return Status();
            case "login":
                return await LoginWithDeviceIdAsync(payload, cancellationToken);
            case "create_lobby":
                return await CreateLobbyAsync(cancellationToken);
            case "join_lobby":
                return await JoinLobbyAsync(ReadRequiredString(payload, "lobbyId"), cancellationToken);
            case "leave_lobby":
                return await LeaveLobbyAsync(cancellationToken);
            case "send_packet":
                return await InvokeOnSdkThreadAsync(() => SendPacket(payload), cancellationToken);
            default:
                throw new InvalidOperationException($"Operazione bridge sconosciuta: {operation}");
        }
    }

    private object Initialize()
    {
        if (_platform is not null) return Status();

        var settings = EosSettings.Load(_settingsPath);
        var initializeOptions = new InitializeOptions
        {
            ProductName = "Holy War",
            ProductVersion = "0.1.1",
        };
        var initializeResult = PlatformInterface.Initialize(ref initializeOptions);
        if (initializeResult is not (Result.Success or Result.AlreadyConfigured))
        {
            throw EosFailure("inizializzazione SDK", initializeResult);
        }

        _sdkInitialized = true;
        LoggingInterface.SetLogLevel(LogCategory.AllCategories, LogLevel.Warning);
        LoggingInterface.SetCallback((ref LogMessage message) =>
            Console.Error.WriteLine($"[EOS:{message.Category}] {message.Message}"));

        var cacheDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "HolyWar",
            "EOS");
        Directory.CreateDirectory(cacheDirectory);
        var platformOptions = new PlatformOptions
        {
            ProductId = settings.ProductId,
            SandboxId = settings.SandboxId,
            DeploymentId = settings.DeploymentId,
            ClientCredentials = new ClientCredentials
            {
                ClientId = settings.ClientId,
                ClientSecret = settings.ClientSecret,
            },
            IsServer = false,
            Flags = PlatformFlags.DisableOverlay,
            EncryptionKey = string.IsNullOrWhiteSpace(settings.EncryptionKey) ? null! : settings.EncryptionKey,
            CacheDirectory = cacheDirectory,
            TickBudgetInMilliseconds = 0,
        };
        _platform = PlatformInterface.Create(ref platformOptions)
            ?? throw new InvalidOperationException("EOS non ha creato l'interfaccia Platform: verifica le credenziali.");
        _connect = _platform.GetConnectInterface();
        _lobby = _platform.GetLobbyInterface();
        _p2p = _platform.GetP2PInterface();

        var relayOptions = new SetRelayControlOptions { RelayControl = RelayControl.AllowRelays };
        var relayResult = _p2p.SetRelayControl(ref relayOptions);
        if (relayResult != Result.Success) throw EosFailure("configurazione relay P2P", relayResult);

        return Status();
    }

    private object Status() => new
    {
        provider = "eos",
        initialized = _platform is not null,
        loggedIn = _localUserId is not null,
        userId = _localUserId?.ToString(),
        lobbyId = _lobbyId,
        ownerId = _ownerId,
        members = _members.Keys.OrderBy(value => value, StringComparer.Ordinal).ToArray(),
    };

    private async Task<object> LoginWithDeviceIdAsync(JsonElement payload, CancellationToken cancellationToken)
    {
        EnsureInitialized();
        if (_localUserId is not null) return new { userId = _localUserId.ToString(), reused = true };

        var displayName = ReadOptionalString(payload, "displayName") ?? Environment.MachineName;
        var createDeviceTcs = CompletionSource<Result>();
        var createDeviceOptions = new CreateDeviceIdOptions { DeviceModel = "Windows PC" };
        await InvokeOnSdkThreadAsync(() =>
            _connect!.CreateDeviceId(ref createDeviceOptions, createDeviceTcs, (ref CreateDeviceIdCallbackInfo info) =>
                createDeviceTcs.TrySetResult(info.ResultCode)), cancellationToken);
        var createDeviceResult = await createDeviceTcs.Task.WaitAsync(cancellationToken);
        if (createDeviceResult is not (Result.Success or Result.DuplicateNotAllowed))
        {
            throw EosFailure("creazione Device ID", createDeviceResult);
        }

        var loginTcs = CompletionSource<DeviceLoginResult>();
        var loginOptions = new ConnectLoginOptions
        {
            Credentials = new ConnectCredentials
            {
                Type = ExternalCredentialType.DeviceidAccessToken,
                Token = null!,
            },
            UserLoginInfo = new UserLoginInfo { DisplayName = displayName },
        };
        await InvokeOnSdkThreadAsync(() =>
            _connect!.Login(ref loginOptions, loginTcs, (ref LoginCallbackInfo info) =>
                loginTcs.TrySetResult(new DeviceLoginResult(info.ResultCode, info.LocalUserId, info.ContinuanceToken))),
            cancellationToken);
        var loginResult = await loginTcs.Task.WaitAsync(cancellationToken);

        if (loginResult.Result == Result.InvalidUser && loginResult.ContinuanceToken is not null)
        {
            var createUserTcs = CompletionSource<UserCreationResult>();
            var createUserOptions = new CreateUserOptions { ContinuanceToken = loginResult.ContinuanceToken };
            await InvokeOnSdkThreadAsync(() =>
                _connect!.CreateUser(ref createUserOptions, createUserTcs, (ref CreateUserCallbackInfo info) =>
                    createUserTcs.TrySetResult(new UserCreationResult(info.ResultCode, info.LocalUserId))),
                cancellationToken);
            var createUserResult = await createUserTcs.Task.WaitAsync(cancellationToken);
            if (createUserResult.Result != Result.Success)
            {
                throw EosFailure("creazione Product User", createUserResult.Result);
            }

            _localUserId = createUserResult.UserId;
        }
        else
        {
            if (loginResult.Result != Result.Success) throw EosFailure("login Device ID", loginResult.Result);
            _localUserId = loginResult.UserId;
        }

        if (_localUserId is null || !_localUserId.IsValid())
        {
            throw new InvalidOperationException("EOS ha restituito un Product User ID non valido.");
        }

        await InvokeOnSdkThreadAsync(RegisterNotifications, cancellationToken);
        _members[_localUserId.ToString()] = 0;
        await RaiseEventAsync("login_complete", new { userId = _localUserId.ToString(), displayName });
        return new { userId = _localUserId.ToString(), displayName };
    }

    private async Task<object> CreateLobbyAsync(CancellationToken cancellationToken)
    {
        EnsureLoggedIn();
        EnsureNoLobby();
        var completion = CompletionSource<LobbyOperationResult>();
        var options = new CreateLobbyOptions
        {
            LocalUserId = _localUserId!,
            MaxLobbyMembers = 2,
            PermissionLevel = LobbyPermissionLevel.Inviteonly,
            PresenceEnabled = false,
            AllowInvites = false,
            BucketId = BucketId,
            DisableHostMigration = true,
            EnableRTCRoom = false,
            EnableJoinById = true,
        };
        await InvokeOnSdkThreadAsync(() =>
            _lobby!.CreateLobby(ref options, completion, (ref CreateLobbyCallbackInfo info) =>
                completion.TrySetResult(new LobbyOperationResult(info.ResultCode, info.LobbyId?.ToString()))),
            cancellationToken);
        var result = await completion.Task.WaitAsync(cancellationToken);
        if (result.Result != Result.Success) throw EosFailure("creazione lobby", result.Result);
        _lobbyId = result.LobbyId ?? throw new InvalidOperationException("EOS non ha restituito il Lobby ID.");
        _ownerId = _localUserId!.ToString();
        await InvokeOnSdkThreadAsync(RefreshLobbyMembers, cancellationToken);
        await RaiseLobbyUpdatedAsync();
        return new { lobbyId = _lobbyId, ownerId = _ownerId, maxMembers = 2 };
    }

    private async Task<object> JoinLobbyAsync(string lobbyId, CancellationToken cancellationToken)
    {
        EnsureLoggedIn();
        EnsureNoLobby();
        var completion = CompletionSource<LobbyOperationResult>();
        var options = new JoinLobbyByIdOptions
        {
            LobbyId = lobbyId,
            LocalUserId = _localUserId!,
            PresenceEnabled = false,
        };
        await InvokeOnSdkThreadAsync(() =>
            _lobby!.JoinLobbyById(ref options, completion, (ref JoinLobbyByIdCallbackInfo info) =>
                completion.TrySetResult(new LobbyOperationResult(info.ResultCode, info.LobbyId?.ToString()))),
            cancellationToken);
        var result = await completion.Task.WaitAsync(cancellationToken);
        if (result.Result != Result.Success) throw EosFailure("accesso alla lobby", result.Result);
        _lobbyId = result.LobbyId ?? lobbyId;
        await InvokeOnSdkThreadAsync(RefreshLobbyMembers, cancellationToken);
        await RaiseLobbyUpdatedAsync();
        return new { lobbyId = _lobbyId, ownerId = _ownerId, maxMembers = 2 };
    }

    private async Task<object> LeaveLobbyAsync(CancellationToken cancellationToken)
    {
        EnsureLoggedIn();
        if (_lobbyId is null) return new { left = true };

        var leavingLobbyId = _lobbyId;
        var completion = CompletionSource<Result>();
        var options = new LeaveLobbyOptions { LocalUserId = _localUserId!, LobbyId = leavingLobbyId };
        await InvokeOnSdkThreadAsync(() =>
            _lobby!.LeaveLobby(ref options, completion, (ref LeaveLobbyCallbackInfo info) =>
                completion.TrySetResult(info.ResultCode)), cancellationToken);
        var result = await completion.Task.WaitAsync(cancellationToken);
        if (result != Result.Success) throw EosFailure("uscita dalla lobby", result);
        _lobbyId = null;
        _ownerId = null;
        _members.Clear();
        _members[_localUserId!.ToString()] = 0;
        return new { left = true };
    }

    private object SendPacket(JsonElement payload)
    {
        EnsureInLobby();
        var data = Encoding.UTF8.GetBytes(ReadRequiredString(payload, "data"));
        if (data.Length > P2PInterface.MAX_PACKET_SIZE)
        {
            throw new InvalidOperationException(
                $"Pacchetto troppo grande: {data.Length} byte; massimo {P2PInterface.MAX_PACKET_SIZE}.");
        }

        var localId = _localUserId!.ToString();
        var remoteIdText = ReadOptionalString(payload, "remoteUserId")
            ?? _members.Keys.FirstOrDefault(member => !member.Equals(localId, StringComparison.Ordinal))
            ?? throw new InvalidOperationException("Nessun altro giocatore presente nella lobby.");
        if (!_members.ContainsKey(remoteIdText))
        {
            throw new InvalidOperationException("Il destinatario P2P non appartiene alla lobby corrente.");
        }

        var remoteId = ProductUserId.FromString(remoteIdText);
        var options = new SendPacketOptions
        {
            LocalUserId = _localUserId,
            RemoteUserId = remoteId,
            SocketId = _socketId,
            Channel = 0,
            Data = new ArraySegment<byte>(data),
            AllowDelayedDelivery = true,
            Reliability = PacketReliability.ReliableOrdered,
            DisableAutoAcceptConnection = false,
        };
        var result = _p2p!.SendPacket(ref options);
        if (result != Result.Success) throw EosFailure("invio pacchetto P2P", result);
        return new { sent = true, bytes = data.Length, remoteUserId = remoteIdText };
    }

    private void RegisterNotifications()
    {
        var lobbyOptions = new AddNotifyLobbyMemberStatusReceivedOptions();
        _lobbyMemberNotificationId = _lobby!.AddNotifyLobbyMemberStatusReceived(
            ref lobbyOptions,
            this,
            (ref LobbyMemberStatusReceivedCallbackInfo info) =>
            {
                var lobbyId = info.LobbyId?.ToString();
                var targetId = info.TargetUserId?.ToString();
                if (_lobbyId is not null && lobbyId == _lobbyId && targetId is not null)
                {
                    if (info.CurrentStatus is LobbyMemberStatus.Joined or LobbyMemberStatus.Promoted)
                    {
                        _members[targetId] = 0;
                    }
                    else
                    {
                        _members.TryRemove(targetId, out _);
                    }

                    if (info.CurrentStatus == LobbyMemberStatus.Promoted) _ownerId = targetId;
                    _ = RaiseEventAsync("lobby_member_status", new
                    {
                        lobbyId,
                        userId = targetId,
                        status = info.CurrentStatus.ToString().ToLowerInvariant(),
                    });
                    _ = RaiseLobbyUpdatedAsync();
                }
            });

        var connectionOptions = new AddNotifyPeerConnectionRequestOptions
        {
            LocalUserId = _localUserId!,
            SocketId = _socketId,
        };
        _connectionRequestNotificationId = _p2p!.AddNotifyPeerConnectionRequest(
            ref connectionOptions,
            this,
            (ref OnIncomingConnectionRequestInfo info) =>
            {
                var remoteId = info.RemoteUserId?.ToString();
                if (remoteId is null || !_members.ContainsKey(remoteId)) return;
                if (info.SocketId?.SocketName != SocketName) return;

                var acceptOptions = new AcceptConnectionOptions
                {
                    LocalUserId = _localUserId!,
                    RemoteUserId = info.RemoteUserId,
                    SocketId = _socketId,
                };
                var result = _p2p.AcceptConnection(ref acceptOptions);
                _ = RaiseEventAsync("peer_connection_request", new
                {
                    remoteUserId = remoteId,
                    accepted = result == Result.Success,
                    result = result.ToString(),
                });
            });
    }

    private void RunSdkThread()
    {
        while (!_tickCancellation.IsCancellationRequested)
        {
            if (_sdkActions.TryTake(out var action, 16))
            {
                action();
            }

            if (_platform is not null)
            {
                _platform.Tick();
                ReceiveAvailablePackets();
            }
        }
    }

    private void ReceiveAvailablePackets()
    {
        if (_localUserId is null || _p2p is null) return;
        while (true)
        {
            var sizeOptions = new GetNextReceivedPacketSizeOptions { LocalUserId = _localUserId };
            var sizeResult = _p2p.GetNextReceivedPacketSize(ref sizeOptions, out var packetSize);
            if (sizeResult == Result.NotFound) return;
            if (sizeResult != Result.Success)
            {
                _ = RaiseEventAsync("transport_error", new { operation = "receive_size", result = sizeResult.ToString() });
                return;
            }

            var buffer = new byte[packetSize];
            ProductUserId peerId = null!;
            var socketId = new SocketId();
            var receiveOptions = new ReceivePacketOptions
            {
                LocalUserId = _localUserId,
                MaxDataSizeBytes = packetSize,
            };
            var receiveResult = _p2p.ReceivePacket(
                ref receiveOptions,
                ref peerId,
                ref socketId,
                out var channel,
                new ArraySegment<byte>(buffer),
                out var bytesWritten);
            if (receiveResult != Result.Success)
            {
                _ = RaiseEventAsync("transport_error", new { operation = "receive", result = receiveResult.ToString() });
                return;
            }

            if (socketId.SocketName != SocketName || !_members.ContainsKey(peerId.ToString())) continue;
            var data = Encoding.UTF8.GetString(buffer, 0, checked((int)bytesWritten));
            _ = RaiseEventAsync("packet_received", new { senderId = peerId.ToString(), channel, data });
        }
    }

    private void RefreshLobbyMembers()
    {
        if (_localUserId is null || _lobbyId is null || _lobby is null) return;
        var copyOptions = new CopyLobbyDetailsHandleOptions
        {
            LobbyId = _lobbyId,
            LocalUserId = _localUserId,
        };
        var copyResult = _lobby.CopyLobbyDetailsHandle(ref copyOptions, out var details);
        if (copyResult != Result.Success || details is null) throw EosFailure("lettura dettagli lobby", copyResult);
        try
        {
            var infoOptions = new LobbyDetailsCopyInfoOptions();
            if (details.CopyInfo(ref infoOptions, out var info) == Result.Success && info.HasValue)
            {
                _ownerId = info.Value.LobbyOwnerUserId?.ToString();
            }

            _members.Clear();
            var countOptions = new LobbyDetailsGetMemberCountOptions();
            var count = details.GetMemberCount(ref countOptions);
            for (uint index = 0; index < count; index++)
            {
                var memberOptions = new LobbyDetailsGetMemberByIndexOptions { MemberIndex = index };
                var member = details.GetMemberByIndex(ref memberOptions);
                if (member is not null) _members[member.ToString()] = 0;
            }
        }
        finally
        {
            details.Release();
        }
    }

    private Task RaiseLobbyUpdatedAsync() => RaiseEventAsync("lobby_updated", new
    {
        lobbyId = _lobbyId,
        ownerId = _ownerId,
        members = _members.Keys.OrderBy(value => value, StringComparer.Ordinal).ToArray(),
    });

    private async Task RaiseEventAsync(string name, object payload)
    {
        var handler = EventRaised;
        if (handler is null) return;
        try
        {
            await handler(name, payload);
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"Errore evento bridge '{name}': {exception.Message}");
        }
    }

    public async ValueTask DisposeAsync()
    {
        await InvokeOnSdkThreadAsync(() =>
        {
            if (_lobbyMemberNotificationId != 0) _lobby?.RemoveNotifyLobbyMemberStatusReceived(_lobbyMemberNotificationId);
            if (_connectionRequestNotificationId != 0) _p2p?.RemoveNotifyPeerConnectionRequest(_connectionRequestNotificationId);
            _platform?.Release();
            _platform = null;
            _connect = null;
            _lobby = null;
            _p2p = null;
            _localUserId = null;
            if (_sdkInitialized) PlatformInterface.Shutdown();
        }, CancellationToken.None);
        _tickCancellation.Cancel();
        _sdkActions.CompleteAdding();
        _sdkThread.Join();
        _sdkActions.Dispose();
        _tickCancellation.Dispose();
    }

    private Task InvokeOnSdkThreadAsync(Action action, CancellationToken cancellationToken) =>
        InvokeOnSdkThreadAsync(() =>
        {
            action();
            return true;
        }, cancellationToken);

    private async Task<T> InvokeOnSdkThreadAsync<T>(Func<T> action, CancellationToken cancellationToken)
    {
        if (Thread.CurrentThread == _sdkThread) return action();
        var completion = CompletionSource<T>();
        _sdkActions.Add(() =>
        {
            try
            {
                completion.TrySetResult(action());
            }
            catch (Exception exception)
            {
                completion.TrySetException(exception);
            }
        }, cancellationToken);
        return await completion.Task.WaitAsync(cancellationToken);
    }

    private void EnsureInitialized()
    {
        if (_platform is null) throw new InvalidOperationException("Bridge EOS non inizializzato.");
    }

    private void EnsureLoggedIn()
    {
        EnsureInitialized();
        if (_localUserId is null) throw new InvalidOperationException("Login EOS richiesto.");
    }

    private void EnsureNoLobby()
    {
        if (_lobbyId is not null) throw new InvalidOperationException("Il giocatore è già in una lobby.");
    }

    private void EnsureInLobby()
    {
        EnsureLoggedIn();
        if (_lobbyId is null) throw new InvalidOperationException("Lobby EOS richiesta.");
    }

    private static InvalidOperationException EosFailure(string operation, Result result) =>
        new($"Errore EOS durante {operation}: {result} ({(int)result}).");

    private static TaskCompletionSource<T> CompletionSource<T>() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private static string ReadRequiredString(JsonElement payload, string name) =>
        ReadOptionalString(payload, name) ?? throw new InvalidOperationException($"Campo richiesto mancante: {name}");

    private static string? ReadOptionalString(JsonElement payload, string name)
    {
        if (payload.ValueKind != JsonValueKind.Object || !payload.TryGetProperty(name, out var value)) return null;
        var result = value.GetString()?.Trim();
        return string.IsNullOrEmpty(result) ? null : result;
    }

    private sealed record DeviceLoginResult(Result Result, ProductUserId? UserId, ContinuanceToken? ContinuanceToken);
    private sealed record UserCreationResult(Result Result, ProductUserId? UserId);
    private sealed record LobbyOperationResult(Result Result, string? LobbyId);
}
