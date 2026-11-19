using Microsoft.UI.Xaml;
using System;
using System.Linq;

namespace divoom_hub_winui3;

public partial class App : Application
{
    private Window? _window;

    public App() => InitializeComponent();

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        if (Environment.GetCommandLineArgs() is [_, "--ui-smoke-test", var report])
        {
            UnhandledException += (_, e) => System.IO.File.WriteAllText(report, e.Exception.ToString());
            UiSmokeTest.Run(report);
            return;
        }
        var instance = Microsoft.Windows.AppLifecycle.AppInstance.FindOrRegisterForKey(Edition.ProfileName);
        if (!instance.IsCurrent)
        {
            await instance.RedirectActivationToAsync(Microsoft.Windows.AppLifecycle.AppInstance.GetCurrent().GetActivatedEventArgs());
            Exit();
            return;
        }
        var main = new MainWindow();
        _window = main;
        instance.Activated += (_, _) => main.DispatcherQueue.TryEnqueue(main.ShowWindow);
        if (Environment.GetCommandLineArgs().Contains("--minimized") && main.Profile.OnboardingCompleted)
            main.HideWindow();
        else main.Activate();
    }
}
