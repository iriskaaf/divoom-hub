using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace divoom_hub_winui3;

// JSON lines: each command has an id. Unsolicited messages have an event name.
internal sealed class PythonBackend
{
    private readonly ConcurrentDictionary<long, TaskCompletionSource<JsonElement>> _pending = new();
    private readonly SemaphoreSlim _writeLock = new(1);
    private Process? _process;
    private long _nextId;
    private bool _stopping;

    public event Action<string, JsonElement, string?>? Event;
    public event Action? Disconnected;

    public void Start()
    {
        var info = new ProcessStartInfo
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        info.Environment["DIVOOM_WINUI_TEST"] = Edition.Test ? "1" : "0";
        string bundled = Path.Combine(AppContext.BaseDirectory, "Backend", "DivoomHub.Backend.exe");
        if (File.Exists(bundled))
            info.FileName = bundled;
        else
        {
            string? source = Environment.GetEnvironmentVariable("DIVOOM_HUB_PYTHON_ROOT");
            for (var folder = new DirectoryInfo(AppContext.BaseDirectory); source is null && folder is not null; folder = folder.Parent)
            {
                foreach (string candidate in new[] { Path.Combine(folder.FullName, "legacy"), Path.Combine(folder.FullName, "VSC", "DIVOOM_SPOTIFY") })
                    if (File.Exists(Path.Combine(candidate, "core", "player.py"))) { source = candidate; break; }
            }
            string worker = Path.Combine(AppContext.BaseDirectory, "Backend", "worker.py");
            if (source is null || !File.Exists(worker))
                throw new IOException("Python-бэкенд не найден.");
            info.FileName = Path.Combine(source, ".venv", "Scripts", "python.exe");
            info.ArgumentList.Add(worker);
            info.ArgumentList.Add(source);
            info.WorkingDirectory = source;
        }
        var process = Process.Start(info) ?? throw new IOException("Не удалось запустить Python.");
        _process = process;
        _ = ReadOutputAsync(process);
        // Drain stderr without displaying raw device or authorization errors.
        _ = process.StandardError.BaseStream.CopyToAsync(Stream.Null);
    }

    public async Task<JsonElement> CallAsync(string command, object? args = null)
    {
        long id = Interlocked.Increment(ref _nextId);
        var answer = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        _pending[id] = answer;
        try
        {
            await WriteAsync(new { id, command, args });
            return await answer.Task.WaitAsync(TimeSpan.FromSeconds(24));
        }
        finally { _pending.TryRemove(id, out _); }
    }

    private async Task WriteAsync(object message)
    {
        await _writeLock.WaitAsync();
        try
        {
            var process = _process ?? throw new IOException("Python-бэкенд не запущен.");
            await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(message, ProfileStore.JsonWire));
            await process.StandardInput.FlushAsync();
        }
        finally { _writeLock.Release(); }
    }

    private async Task ReadOutputAsync(Process process)
    {
        try
        {
            while (await process.StandardOutput.ReadLineAsync() is string line)
            {
                using var document = JsonDocument.Parse(line);
                var message = document.RootElement;
                if (message.TryGetProperty("event", out var name))
                    Event?.Invoke(name.GetString()!, message.GetProperty("data").Clone(),
                        message.TryGetProperty("device", out var device) ? device.GetString() : null);
                else if (message.TryGetProperty("id", out var id) && _pending.TryRemove(id.GetInt64(), out var answer))
                {
                    if (message.TryGetProperty("error", out var error)) answer.TrySetException(new BackendException(error.GetString()!));
                    else answer.TrySetResult(message.GetProperty("data").Clone());
                }
            }
        }
        catch (Exception e) when (e is IOException or JsonException or ObjectDisposedException or InvalidOperationException) { }
        finally
        {
            foreach (var item in _pending.Values) item.TrySetException(new IOException("Python-бэкенд отключён."));
            if (!_stopping) Disconnected?.Invoke();
        }
    }

    public async Task StopAsync()
    {
        _stopping = true;
        var process = _process;
        if (process is null) return;
        try
        {
            if (!process.HasExited)
            {
                await WriteAsync(new { command = "shutdown" });
                process.StandardInput.Close();
                await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(14));
            }
        }
        catch (Exception e) when (e is IOException or InvalidOperationException or TimeoutException)
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
        }
        finally { _process = null; process.Dispose(); }
    }
}

internal sealed class BackendException(string message) : Exception(message);
