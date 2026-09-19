using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace RobloxToolLauncher;

public sealed class MainForm : Form
{
    private readonly TextBox scraperPath = new();
    private readonly ComboBox outputPath = new();
    private readonly NumericUpDown limitInput = new();
    private readonly NumericUpDown workersInput = new();
    private readonly NumericUpDown thumbnailsInput = new();
    private readonly CheckBox visualSearchInput = new();
    private readonly CheckBox autoOpenInput = new();
    private readonly CheckBox scheduleInput = new();
    private readonly DateTimePicker scheduleTime = new();
    private readonly ComboBox profileInput = new();
    private readonly Button runButton = new();
    private readonly Button cancelButton = new();
    private readonly Button openGalleryButton = new();
    private readonly ProgressBar progressBar = new();
    private readonly Label progressLabel = new();
    private readonly RichTextBox logBox = new();
    private readonly ListBox historyList = new();
    private readonly System.Windows.Forms.Timer scheduleTimer = new() { Interval = 15000 };
    private readonly string settingsDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RobloxThumbnailScraperLauncher");
    private Process? runningProcess;
    private DateTime lastScheduledRun = DateTime.MinValue;

    public MainForm()
    {
        Text = "roblox thumbnail scraper";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(820, 650);
        Size = new Size(980, 760);
        Font = new Font("Segoe UI", 10F);
        FormClosing += (_, _) =>
        {
            if (runningProcess is not null && !runningProcess.HasExited)
            {
                runningProcess.Kill(true);
            }
        };

        ConfigureInputs();
        BuildLayout();
        LoadProfiles();
        LoadHistory();
        scheduleTimer.Tick += (_, _) => CheckSchedule();
        scheduleTimer.Start();
    }

    private void ConfigureInputs()
    {
        scraperPath.Text = FindScraper();
        outputPath.DropDownStyle = ComboBoxStyle.DropDown;
        outputPath.AutoCompleteMode = AutoCompleteMode.SuggestAppend;
        outputPath.AutoCompleteSource = AutoCompleteSource.ListItems;
        outputPath.Text = Path.Combine(AppContext.BaseDirectory, "output");
        limitInput.Minimum = 1;
        limitInput.Maximum = 5000;
        limitInput.Value = 50;
        workersInput.Minimum = 1;
        workersInput.Maximum = 16;
        workersInput.Value = 1;
        thumbnailsInput.Minimum = 1;
        thumbnailsInput.Maximum = 10;
        thumbnailsInput.Value = 10;
        visualSearchInput.Text = "Enable local visual search";
        visualSearchInput.AutoSize = true;
        autoOpenInput.Text = "Open gallery when finished";
        autoOpenInput.AutoSize = true;
        scheduleInput.Text = "Run every day at";
        scheduleInput.AutoSize = true;
        scheduleTime.Format = DateTimePickerFormat.Custom;
        scheduleTime.CustomFormat = "HH:mm";
        scheduleTime.ShowUpDown = true;
        scheduleTime.Value = DateTime.Today.AddHours(3);
        profileInput.DropDownStyle = ComboBoxStyle.DropDown;
        profileInput.AutoCompleteMode = AutoCompleteMode.SuggestAppend;
        profileInput.AutoCompleteSource = AutoCompleteSource.ListItems;
        profileInput.SelectedIndexChanged += (_, _) => LoadSelectedProfile();
        runButton.Text = "Run scraper";
        runButton.AutoSize = true;
        runButton.Click += async (_, _) => await RunScraperAsync();
        cancelButton.Text = "Cancel";
        cancelButton.AutoSize = true;
        cancelButton.Enabled = false;
        cancelButton.Click += (_, _) => CancelScraper();
        openGalleryButton.Text = "Open gallery";
        openGalleryButton.AutoSize = true;
        openGalleryButton.Enabled = false;
        openGalleryButton.Click += (_, _) => OpenGallery();
        progressBar.Minimum = 0;
        progressBar.Maximum = 100;
        progressBar.Dock = DockStyle.Fill;
        progressLabel.Text = "Ready";
        progressLabel.AutoSize = true;
        progressLabel.Anchor = AnchorStyles.Left;
        logBox.ReadOnly = true;
        logBox.BackColor = Color.FromArgb(30, 30, 30);
        logBox.ForeColor = Color.Gainsboro;
        logBox.Dock = DockStyle.Fill;
        historyList.Dock = DockStyle.Fill;
        historyList.DoubleClick += (_, _) =>
        {
            if (historyList.SelectedItem is string path && Directory.Exists(path))
            {
                outputPath.Text = path;
            }
        };
    }

    private void BuildLayout()
    {
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(18),
            ColumnCount = 3,
            RowCount = 12,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 160));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 130));
        for (var index = 0; index < 11; index++)
        {
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, index is 8 or 9 ? 42 : 38));
        }
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        AddRow(layout, 0, "Scraper EXE", scraperPath, CreateBrowseButton(BrowseScraper));
        AddRow(layout, 1, "Output folder", outputPath, CreateBrowseButton(BrowseOutput));
        AddRow(layout, 2, "Games to scrape", limitInput, new Label());
        AddRow(layout, 3, "Workers", workersInput, new Label());
        AddRow(layout, 4, "Thumbnails per game", thumbnailsInput, new Label());
        AddRow(layout, 5, "Profile", profileInput, CreateProfileButton());
        layout.Controls.Add(visualSearchInput, 1, 6);
        layout.SetColumnSpan(visualSearchInput, 2);
        layout.Controls.Add(autoOpenInput, 1, 7);
        layout.SetColumnSpan(autoOpenInput, 2);

        var schedulePanel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, WrapContents = false };
        schedulePanel.Controls.Add(scheduleInput);
        schedulePanel.Controls.Add(scheduleTime);
        layout.Controls.Add(schedulePanel, 1, 8);
        layout.SetColumnSpan(schedulePanel, 2);

        var actionPanel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, WrapContents = false };
        actionPanel.Controls.Add(runButton);
        actionPanel.Controls.Add(cancelButton);
        actionPanel.Controls.Add(openGalleryButton);
        layout.Controls.Add(actionPanel, 1, 9);
        layout.SetColumnSpan(actionPanel, 2);

        var progressPanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        progressPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        progressPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 170));
        progressPanel.Controls.Add(progressBar, 0, 0);
        progressPanel.Controls.Add(progressLabel, 1, 0);
        layout.Controls.Add(progressPanel, 0, 10);
        layout.SetColumnSpan(progressPanel, 3);

        var split = new SplitContainer { Dock = DockStyle.Fill, Orientation = Orientation.Vertical, SplitterDistance = 650 };
        split.Panel1.Controls.Add(logBox);
        split.Panel2.Controls.Add(historyList);
        layout.Controls.Add(split, 0, 11);
        layout.SetColumnSpan(split, 3);
        Controls.Add(layout);
    }

    private static void AddRow(TableLayoutPanel layout, int row, string labelText, Control input, Control action)
    {
        var label = new Label { Text = labelText, AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(0, 8, 0, 0) };
        input.Dock = DockStyle.Fill;
        input.Margin = new Padding(3, 3, 8, 3);
        action.Dock = DockStyle.Fill;
        action.Margin = new Padding(0, 3, 0, 3);
        layout.Controls.Add(label, 0, row);
        layout.Controls.Add(input, 1, row);
        layout.Controls.Add(action, 2, row);
    }

    private Button CreateBrowseButton(EventHandler handler)
    {
        var button = new Button { Text = "Browse...", AutoSize = true };
        button.Click += handler;
        return button;
    }

    private Control CreateProfileButton()
    {
        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, WrapContents = false };
        var save = new Button { Text = "Save", AutoSize = true };
        var delete = new Button { Text = "Delete", AutoSize = true };
        save.Click += (_, _) => SaveProfile();
        delete.Click += (_, _) => DeleteProfile();
        panel.Controls.Add(save);
        panel.Controls.Add(delete);
        return panel;
    }

    private void BrowseScraper(object? sender, EventArgs e)
    {
        using var dialog = new OpenFileDialog { Filter = "Windows executable (*.exe)|*.exe|All files (*.*)|*.*" };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            scraperPath.Text = dialog.FileName;
        }
    }

    private void BrowseOutput(object? sender, EventArgs e)
    {
        using var dialog = new FolderBrowserDialog { SelectedPath = outputPath.Text };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            outputPath.Text = dialog.SelectedPath;
        }
    }

    private async Task RunScraperAsync()
    {
        if (runningProcess is not null)
        {
            return;
        }

        var executable = scraperPath.Text.Trim();
        if (!File.Exists(executable))
        {
            MessageBox.Show(this, "Choose the roblox_thumbnail_scraper.exe file first.", "Scraper not found", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var destination = outputPath.Text.Trim();
        if (string.IsNullOrWhiteSpace(destination))
        {
            MessageBox.Show(this, "Choose an output folder first.", "Output folder missing", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        Directory.CreateDirectory(destination);
        AddRecentOutput(destination);
        logBox.Clear();
        progressBar.Value = 0;
        progressLabel.Text = "Starting";
        openGalleryButton.Enabled = false;
        runButton.Enabled = false;
        cancelButton.Enabled = true;
        AppendLog("Starting scraper...");

        var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = executable,
                WorkingDirectory = Path.GetDirectoryName(executable) ?? AppContext.BaseDirectory,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            },
            EnableRaisingEvents = true,
        };
        process.StartInfo.ArgumentList.Add("--limit");
        process.StartInfo.ArgumentList.Add(limitInput.Value.ToString(CultureInfo.InvariantCulture));
        process.StartInfo.ArgumentList.Add("--workers");
        process.StartInfo.ArgumentList.Add(workersInput.Value.ToString(CultureInfo.InvariantCulture));
        process.StartInfo.ArgumentList.Add("--count-per-universe");
        process.StartInfo.ArgumentList.Add(thumbnailsInput.Value.ToString(CultureInfo.InvariantCulture));
        process.StartInfo.ArgumentList.Add("--output");
        process.StartInfo.ArgumentList.Add(destination);
        if (visualSearchInput.Checked)
        {
            process.StartInfo.ArgumentList.Add("--visual-search");
        }

        process.OutputDataReceived += (_, args) =>
        {
            AppendLog(args.Data);
            UpdateProgress(args.Data);
        };
        process.ErrorDataReceived += (_, args) => AppendLog(args.Data);
        runningProcess = process;
        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException("The scraper process could not start.");
            }
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            await process.WaitForExitAsync();
            AppendLog($"Finished with exit code {process.ExitCode}.");
            progressLabel.Text = process.ExitCode == 0 ? "Finished" : "Failed";
            progressBar.Value = process.ExitCode == 0 ? 100 : progressBar.Value;
            openGalleryButton.Enabled = HasGallery(destination);
            AddHistory(destination, process.ExitCode);
            if (process.ExitCode == 0 && autoOpenInput.Checked)
            {
                OpenGallery();
            }
        }
        catch (Exception exception)
        {
            AppendLog(exception.Message);
            progressLabel.Text = "Error";
            MessageBox.Show(this, exception.Message, "Launcher error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            process.Dispose();
            runningProcess = null;
            runButton.Enabled = true;
            cancelButton.Enabled = false;
        }
    }

    private void CancelScraper()
    {
        if (runningProcess is null || runningProcess.HasExited)
        {
            return;
        }
        AppendLog("Cancelling scraper...");
        runningProcess.Kill(true);
        progressLabel.Text = "Cancelled";
    }

    private void UpdateProgress(string? message)
    {
        if (string.IsNullOrWhiteSpace(message))
        {
            return;
        }
        var match = Regex.Match(message, @"(?:Downloaded|Analyzed)\s+(\d+)\s*/\s*(\d+)", RegexOptions.IgnoreCase);
        if (!match.Success || !int.TryParse(match.Groups[1].Value, out var current) || !int.TryParse(match.Groups[2].Value, out var total) || total <= 0)
        {
            return;
        }
        var value = Math.Clamp(current * 100 / total, 0, 100);
        if (InvokeRequired)
        {
            BeginInvoke(() => UpdateProgress(message));
            return;
        }
        progressBar.Value = value;
        progressLabel.Text = $"{current}/{total}";
    }

    private void AppendLog(string? message)
    {
        if (string.IsNullOrWhiteSpace(message) || IsDisposed)
        {
            return;
        }
        if (InvokeRequired)
        {
            BeginInvoke(() => AppendLog(message));
            return;
        }
        logBox.AppendText(message + Environment.NewLine);
        logBox.ScrollToCaret();
    }

    private void OpenGallery()
    {
        var destination = outputPath.Text.Trim();
        var nativeGallery = FindGallery();
        if (File.Exists(nativeGallery) && Directory.Exists(destination))
        {
            Process.Start(new ProcessStartInfo { FileName = nativeGallery, ArgumentList = { destination }, UseShellExecute = true });
            return;
        }
        var html = Path.Combine(destination, "index.html");
        if (File.Exists(html))
        {
            Process.Start(new ProcessStartInfo { FileName = html, UseShellExecute = true });
            return;
        }
        MessageBox.Show(this, "Run the scraper first.", "Gallery not found", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private static bool HasGallery(string destination)
    {
        return File.Exists(Path.Combine(destination, "index.html")) || File.Exists(Path.Combine(AppContext.BaseDirectory, "RobloxThumbnailGallery.exe")) || File.Exists(Path.Combine(AppContext.BaseDirectory, "gallery", "RobloxThumbnailGallery.exe"));
    }

    private static string FindGallery()
    {
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "RobloxThumbnailGallery.exe"),
            Path.Combine(AppContext.BaseDirectory, "gallery", "RobloxThumbnailGallery.exe"),
            Path.Combine(desktop, "Roblox Thumbnail Scraper", "gallery", "publish", "RobloxThumbnailGallery.exe"),
        };
        return candidates.FirstOrDefault(File.Exists) ?? string.Empty;
    }

    private static string FindScraper()
    {
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "roblox_thumbnail_scraper.exe"),
            Path.Combine(desktop, "Roblox Thumbnail Scraper", "downloads", "roblox_thumbnail_scraper.exe"),
            Path.Combine(Directory.GetCurrentDirectory(), "roblox_thumbnail_scraper.exe"),
        };
        return candidates.FirstOrDefault(File.Exists) ?? string.Empty;
    }

    private string ProfilesFile => Path.Combine(settingsDirectory, "profiles.json");
    private string HistoryFile => Path.Combine(settingsDirectory, "history.json");

    private void SaveProfile()
    {
        var name = profileInput.Text.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            MessageBox.Show(this, "Type a profile name first.", "Profile name missing", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        var profiles = ReadJson<List<LauncherProfile>>(ProfilesFile) ?? new List<LauncherProfile>();
        profiles.RemoveAll(item => string.Equals(item.Name, name, StringComparison.OrdinalIgnoreCase));
        profiles.Add(new LauncherProfile
        {
            Name = name,
            ScraperPath = scraperPath.Text,
            OutputPath = outputPath.Text,
            Limit = limitInput.Value,
            Workers = workersInput.Value,
            Thumbnails = thumbnailsInput.Value,
            VisualSearch = visualSearchInput.Checked,
            AutoOpen = autoOpenInput.Checked,
        });
        WriteJson(ProfilesFile, profiles);
        LoadProfiles();
        profileInput.Text = name;
        AppendLog($"Saved profile: {name}");
    }

    private void DeleteProfile()
    {
        var name = profileInput.Text.Trim();
        var profiles = ReadJson<List<LauncherProfile>>(ProfilesFile) ?? new List<LauncherProfile>();
        profiles.RemoveAll(item => string.Equals(item.Name, name, StringComparison.OrdinalIgnoreCase));
        WriteJson(ProfilesFile, profiles);
        LoadProfiles();
    }

    private void LoadProfiles()
    {
        var selected = profileInput.Text;
        profileInput.Items.Clear();
        var profiles = ReadJson<List<LauncherProfile>>(ProfilesFile) ?? new List<LauncherProfile>();
        foreach (var profile in profiles.OrderBy(item => item.Name))
        {
            profileInput.Items.Add(profile.Name);
        }
        profileInput.Text = selected;
    }

    private void LoadSelectedProfile()
    {
        var name = profileInput.Text.Trim();
        var profile = (ReadJson<List<LauncherProfile>>(ProfilesFile) ?? new List<LauncherProfile>()).FirstOrDefault(item => string.Equals(item.Name, name, StringComparison.OrdinalIgnoreCase));
        if (profile is null)
        {
            return;
        }
        scraperPath.Text = profile.ScraperPath;
        outputPath.Text = profile.OutputPath;
        limitInput.Value = Clamp(profile.Limit, limitInput.Minimum, limitInput.Maximum);
        workersInput.Value = Clamp(profile.Workers, workersInput.Minimum, workersInput.Maximum);
        thumbnailsInput.Value = Clamp(profile.Thumbnails, thumbnailsInput.Minimum, thumbnailsInput.Maximum);
        visualSearchInput.Checked = profile.VisualSearch;
        autoOpenInput.Checked = profile.AutoOpen;
    }

    private void AddRecentOutput(string path)
    {
        if (!outputPath.Items.Contains(path))
        {
            outputPath.Items.Insert(0, path);
        }
        while (outputPath.Items.Count > 10)
        {
            outputPath.Items.RemoveAt(outputPath.Items.Count - 1);
        }
    }

    private void AddHistory(string path, int exitCode)
    {
        var history = ReadJson<List<HistoryEntry>>(HistoryFile) ?? new List<HistoryEntry>();
        history.Insert(0, new HistoryEntry { Path = path, FinishedAt = DateTimeOffset.Now, ExitCode = exitCode });
        WriteJson(HistoryFile, history.Take(20).ToList());
        LoadHistory();
    }

    private void LoadHistory()
    {
        historyList.Items.Clear();
        var history = ReadJson<List<HistoryEntry>>(HistoryFile) ?? new List<HistoryEntry>();
        foreach (var entry in history)
        {
            historyList.Items.Add($"{entry.FinishedAt.LocalDateTime:g}  {(entry.ExitCode == 0 ? "OK" : "Failed")}\n{entry.Path}");
        }
    }

    private void CheckSchedule()
    {
        if (!scheduleInput.Checked || runningProcess is not null)
        {
            return;
        }
        var now = DateTime.Now;
        if (now.Hour != scheduleTime.Value.Hour || now.Minute != scheduleTime.Value.Minute || lastScheduledRun.Date == now.Date)
        {
            return;
        }
        lastScheduledRun = now;
        _ = RunScraperAsync();
    }

    private static decimal Clamp(decimal value, decimal minimum, decimal maximum)
    {
        return Math.Min(Math.Max(value, minimum), maximum);
    }

    private static T? ReadJson<T>(string path)
    {
        try
        {
            return File.Exists(path) ? JsonSerializer.Deserialize<T>(File.ReadAllText(path)) : default;
        }
        catch
        {
            return default;
        }
    }

    private void WriteJson<T>(string path, T value)
    {
        Directory.CreateDirectory(settingsDirectory);
        File.WriteAllText(path, JsonSerializer.Serialize(value, new JsonSerializerOptions { WriteIndented = true }));
    }

    private sealed class LauncherProfile
    {
        public string Name { get; set; } = string.Empty;
        public string ScraperPath { get; set; } = string.Empty;
        public string OutputPath { get; set; } = string.Empty;
        public decimal Limit { get; set; }
        public decimal Workers { get; set; }
        public decimal Thumbnails { get; set; }
        public bool VisualSearch { get; set; }
        public bool AutoOpen { get; set; }
    }

    private sealed class HistoryEntry
    {
        public string Path { get; set; } = string.Empty;
        public DateTimeOffset FinishedAt { get; set; }
        public int ExitCode { get; set; }
    }
}
