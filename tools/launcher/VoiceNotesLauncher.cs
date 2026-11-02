// VoiceNotesLauncher.cs
// Tiny tray icon that starts Voice Notes on demand, so the app itself no longer
// has to run from login. Runs at logon from the Startup folder (~10 MB RAM).
//
//   Left-click the icon  -> start Voice Notes
//   Right-click          -> Start Voice Notes / Exit launcher
//
// The icon hides itself while Voice Notes is running (the app has its own tray
// icon) and comes back when the app exits. "Running" is decided by the app's own
// single-instance mutex, same as tools\watchdog.py, so this never starts a duplicate.
//
// Build (no SDK needed, uses the .NET Framework compiler that ships with Windows):
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:winexe
//     /out:VoiceNotesLauncher.exe /r:System.Windows.Forms.dll /r:System.Drawing.dll
//     VoiceNotesLauncher.cs
using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Security.AccessControl;
using System.Threading;
using System.Windows.Forms;

static class VoiceNotesLauncher
{
    const string AppMutex = "VoiceNotes_SingleInstance_v1";   // must match main.py

    // Project root is resolved at runtime so the repo is portable across machines:
    // use VOICE_NOTES_ROOT if it is set, else walk up from the launcher's own folder
    // to the directory that contains main.py, else fall back to that folder. (If you
    // copy the exe into the Startup folder, set VOICE_NOTES_ROOT, because main.py is
    // then no longer one of its parent folders.)
    static readonly string Root = ResolveRoot();

    static NotifyIcon tray;

    static string ResolveRoot()
    {
        string env = Environment.GetEnvironmentVariable("VOICE_NOTES_ROOT");
        if (!string.IsNullOrEmpty(env) && File.Exists(Path.Combine(env, "main.py")))
            return env;
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        for (var d = new DirectoryInfo(dir); d != null; d = d.Parent)
            if (File.Exists(Path.Combine(d.FullName, "main.py")))
                return d.FullName;
        return dir.TrimEnd(Path.DirectorySeparatorChar);
    }

    [STAThread]
    static void Main()
    {
        bool first;
        using (new Mutex(true, "VoiceNotesLauncher_SingleInstance", out first))
        {
            if (!first) return;

            Application.EnableVisualStyles();
            var menu = new ContextMenuStrip();
            menu.Items.Add("Start Voice Notes", null, delegate { Launch(); });
            menu.Items.Add("Exit launcher", null, delegate { tray.Visible = false; Application.Exit(); });

            tray = new NotifyIcon();
            tray.Icon = MakeIcon();
            tray.Text = "Voice Notes (off) - click to start";
            tray.ContextMenuStrip = menu;
            tray.MouseClick += delegate(object s, MouseEventArgs e) { if (e.Button == MouseButtons.Left) Launch(); };
            tray.Visible = !AppRunning();

            var poll = new System.Windows.Forms.Timer();
            poll.Interval = 3000;
            poll.Tick += delegate { tray.Visible = !AppRunning(); };
            poll.Start();

            Application.Run();
        }
    }

    static bool AppRunning()
    {
        try
        {
            Mutex m;
            if (Mutex.TryOpenExisting(AppMutex, MutexRights.Synchronize, out m)) { m.Dispose(); return true; }
            return false;
        }
        catch (UnauthorizedAccessException) { return true; }   // exists, just not openable
    }

    static void Launch()
    {
        if (AppRunning()) { tray.Visible = false; return; }
        string pythonw = Path.Combine(Root, @".venv\Scripts\pythonw.exe");
        if (!File.Exists(pythonw))
        {
            tray.ShowBalloonTip(4000, "Voice Notes", "Missing " + pythonw, ToolTipIcon.Error);
            return;
        }
        // Shell launch, same as the old Startup shortcut: no std handles, so under
        // pythonw sys.stdout stays None and main.py logs to app.log.
        var psi = new ProcessStartInfo(pythonw, "main.py");
        psi.WorkingDirectory = Root;
        psi.UseShellExecute = true;
        psi.WindowStyle = ProcessWindowStyle.Hidden;
        Process.Start(psi);
        tray.Text = "Voice Notes - starting...";
    }

    // Red circle with a white microphone, drawn at runtime so there is no .ico to ship.
    static Icon MakeIcon()
    {
        var bmp = new Bitmap(32, 32);
        using (var g = Graphics.FromImage(bmp))
        using (var white = new SolidBrush(Color.White))
        using (var pen = new Pen(Color.White, 2.5f))
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.Clear(Color.Transparent);
            using (var red = new SolidBrush(Color.FromArgb(229, 72, 77))) g.FillEllipse(red, 0, 0, 31, 31);
            using (var capsule = new GraphicsPath())
            {
                capsule.AddArc(12, 6, 8, 8, 180, 180);
                capsule.AddArc(12, 12, 8, 8, 0, 180);
                capsule.CloseFigure();
                g.FillPath(white, capsule);
            }
            g.DrawArc(pen, 9, 9, 14, 13, 0, 180);
            g.DrawLine(pen, 16, 22, 16, 26);
            g.DrawLine(pen, 12, 26, 20, 26);
        }
        return Icon.FromHandle(bmp.GetHicon());
    }
}
