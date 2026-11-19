using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using System;
using System.IO;
using System.Collections.Generic;
using Windows.UI;

namespace divoom_hub_winui3;

internal static class ClockPreview
{
    public static UIElement FromFrames(BitmapImage?[] frames, double size = 104)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5 };
        foreach (var frame in frames)
            row.Children.Add(new Border { Width = size, Height = size, Background = Brush("#141414"),
                Child = new Image { Source = frame, Stretch = Stretch.UniformToFill } });
        return new Viewbox { Child = row, StretchDirection = StretchDirection.DownOnly, HorizontalAlignment = HorizontalAlignment.Left };
    }

    // Local approximation. The actual device frames will come from Python.
    public static UIElement Create(ClockFace face, string mode, bool format24 = true, string[]? sides = null, bool sample = false)
    {
        bool compact = mode == "gifs_clock";
        if (mode is "device" or "off")
            return Form.Text(mode == "device" ? "Циферблат на самом Times Gate" : "Программа не управляет экранами");
        string time = sample ? "12:34" : DateTime.Now.ToString(format24 ? "HH':'mm" : "hh':'mm");
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5 };
        if (sample && compact) row.Children.Add(Tile(face, time[..2] + "\n" + time[3..], 2, true));
        else for (int i = 0; i < 5; i++)
        {
            UIElement tile = compact && i != 2
                ? MediaTile(sides is { Length: 4 } ? sides[i < 2 ? i : i - 1] : "") ?? Tile(face, "", i, true)
                : Tile(face, compact ? time[..2] + "\n" + time[3..] : time[i].ToString(), i, compact);
            row.Children.Add(tile);
        }
        return new Viewbox { Child = row, StretchDirection = StretchDirection.DownOnly, HorizontalAlignment = HorizontalAlignment.Left };
    }

    public static SolidColorBrush Brush(string hex) => new(Parse(hex));
    public static Color Parse(string hex)
    {
        if (hex.Length == 7 && hex[0] == '#' && uint.TryParse(hex.AsSpan(1),
            System.Globalization.NumberStyles.HexNumber, null, out uint rgb))
            return Color.FromArgb(255, (byte)(rgb >> 16), (byte)(rgb >> 8), (byte)rgb);
        return Color.FromArgb(255, 24, 24, 24);
    }
    public static string Hex(Color color) => $"#{color.R:X2}{color.G:X2}{color.B:X2}";

    private static UIElement Tile(ClockFace face, string label, int pos, bool compact)
    {
        if (face.Style == "custom" && face.Chars.TryGetValue(label, out var path) && MediaTile(path) is Border media) return media;
        string Value(string key, string fallback) => face.Palette.GetValueOrDefault(key, fallback);
        char digit = label.Length == 0 ? '0' : label[0];
        (string bg, string ink) = face.Style switch
        {
            "swiss" => (label == ":" ? Value("dark", "#141414") : Value("t" + digit, "#1858FF"), Value("light", "#F0EDE4")),
            "glass" => (Value("bg", "#0E0F22"), Value("digit", "#F5F5FF")),
            "crt" => (Value("screen", "#071E12"), Value("phosphor", "#54E49A")),
            "serif" => (Value("paper", "#F3EEE2"), Value(label == ":" ? "accent" : "ink", "#241E1C")),
            "gameboy" => (Value("lightest", "#92B623"), Value("darkest", "#193700")),
            "soft" => ("#000000", Value("digit", "#233F33")),
            _ => (Value("bg", "#101010"), Value("color", "#F5F5F5"))
        };
        if (face.Style == "swiss")
        {
            var tone = Parse(bg);
            bool bright = tone.R * .299 + tone.G * .587 + tone.B * .114 > 150;
            ink = label == ":" ? Value("accent", "#FF4E31") : bright ? Value("dark", "#111111") : ink;
        }
        var text = new TextBlock { Text = label, HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center, Foreground = Brush(ink), TextAlignment = TextAlignment.Center,
            FontSize = compact ? 28 : 48, LineHeight = compact ? 30 : 52,
            FontFamily = new FontFamily(face.Style switch { "serif" => "Georgia", "crt" or "gameboy" => "Consolas", _ => "Segoe UI" }),
            FontWeight = face.Style == "serif" ? Microsoft.UI.Text.FontWeights.Normal : Microsoft.UI.Text.FontWeights.Bold };
        if (face.Style == "serif") text.FontStyle = Windows.UI.Text.FontStyle.Italic;
        UIElement child = text;
        Brush fill = Brush(bg);
        Thickness border = new(0);
        Brush? edge = null;
        if (face.Style == "glass")
        {
            var gradient = new LinearGradientBrush { StartPoint = new Windows.Foundation.Point(0, 0),
                EndPoint = new Windows.Foundation.Point(1, 1) };
            gradient.GradientStops.Add(new GradientStop { Color = Parse(bg), Offset = 0 });
            gradient.GradientStops.Add(new GradientStop { Color = Parse(Value("b" + (pos % 3 + 1), "#2F6FE0")), Offset = .56 });
            gradient.GradientStops.Add(new GradientStop { Color = Parse(Value("bg2", "#1B1237")), Offset = 1 });
            fill = gradient;
            child = new Border { Child = text, Margin = new Thickness(7), CornerRadius = new CornerRadius(14),
                Background = new SolidColorBrush(Color.FromArgb(56, 255, 255, 255)), BorderThickness = new Thickness(1),
                BorderBrush = new SolidColorBrush(Color.FromArgb(92, 255, 255, 255)) };
        }
        else if (face.Style == "crt")
        {
            border = new Thickness(5);
            edge = Brush(Value("case", "#24241C"));
        }
        else if (face.Style == "gameboy")
        {
            border = new Thickness(3);
            edge = Brush(Value("dark", "#306230"));
            if (label == ":") fill = Brush(Value("light", "#8BAC0F"));
        }
        else if (face.Style == "serif")
        {
            border = new Thickness(0, 1, 0, 1);
            edge = Brush(Value("rule", "#C3BFB5"));
            var sheet = new Grid();
            sheet.Children.Add(text);
            sheet.Children.Add(new TextBlock { Text = label == ":" ? "ВРЕМЯ" : "№ " + digit, FontSize = 8,
                Margin = new Thickness(4), Foreground = Brush(Value("note", "#776C64")) });
            sheet.Children.Add(new Border { Width = 4, Height = 4, Margin = new Thickness(5), CornerRadius = new CornerRadius(2),
                Background = Brush(Value("accent", "#C0532F")), HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Bottom });
            child = sheet;
        }
        if (face.Style == "soft" && label.Length > 0)
        {
            string shape = Value("shape", "#C6D8B8");
            child = new Border { Child = text, Margin = new Thickness(8), Background = Brush(shape),
                CornerRadius = digit is '0' or '3' or '6' or '9' ? new CornerRadius(40) : digit is '1' or '4' or '7' or ':'
                ? new CornerRadius(28, 8, 28, 8) : new CornerRadius(16) };
        }
        return new Border { Width = 82, Height = 82, Background = fill, Child = child, BorderBrush = edge, BorderThickness = border,
            CornerRadius = new CornerRadius(face.Style is "crt" or "glass" ? 12 : 4) };
    }

    private static Border? MediaTile(string path)
    {
        if (!Path.IsPathFullyQualified(path) || !File.Exists(path) || !Uri.TryCreate(path, UriKind.Absolute, out var uri)) return null;
        return new Border { Width = 82, Height = 82, Background = Brush("#121212"),
            Child = new Image { Source = new BitmapImage(uri) { DecodePixelWidth = 160 }, Stretch = Stretch.UniformToFill } };
    }
}
