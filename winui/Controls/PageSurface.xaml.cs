using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System;

namespace divoom_hub_winui3;

public sealed partial class PageSurface : UserControl
{
    private Action? _back;
    internal PageSurface(string title, Action? back = null)
    {
        InitializeComponent();
        Heading.Text = title;
        _back = back;
        BackButton.Visibility = back is null ? Visibility.Collapsed : Visibility.Visible;
    }

    internal void Add(UIElement element) => Body.Children.Add(element);
    internal void CenterSetup()
    {
        Layout.VerticalAlignment = VerticalAlignment.Center;
        Scroller.SizeChanged += (_, e) => ContentArea.MinHeight = e.NewSize.Height;
        Layout.MaxWidth = 880;
        HeadingRow.HorizontalAlignment = HorizontalAlignment.Center;
        Heading.TextAlignment = TextAlignment.Center;
        Heading.TextWrapping = TextWrapping.Wrap;
        Heading.FontSize = 32;
    }
    internal void SetTitle(string title) => Heading.Text = title;
    internal void ShowStatus(MainWindow window, DeviceLive state)
    {
        StatusDot.Visibility = Visibility.Visible;
        Observe(window, () =>
        {
            StatusDot.Fill = MainWindow.StatusColor(state.Online);
            ToolTipService.SetToolTip(StatusDot, state.Status);
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(StatusDot, state.Status);
        });
    }

    internal void Observe(MainWindow window, Action update)
    {
        Loaded += (_, _) => { window.LiveChanged += update; update(); };
        Unloaded += (_, _) => window.LiveChanged -= update;
    }

    internal void Message(string text, InfoBarSeverity severity = InfoBarSeverity.Informational)
    {
        Notice.Message = text;
        Notice.Severity = severity;
        Notice.IsOpen = true;
        Notice.Visibility = Visibility.Visible;
    }

    private void GoBack(object sender, RoutedEventArgs e) => _back?.Invoke();
}
