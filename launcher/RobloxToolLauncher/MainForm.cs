using System.Diagnostics;
using System.Globalization;

namespace RobloxToolLauncher;

public sealed class MainForm : Form
{
    private readonly TextBox scraperPath = new();
    private readonly TextBox outputPath = new();
    private readonly NumericUpDown limitInput = new();
    private readonly NumericUpDown workersInput = new();
    private readonly NumericUpDown thumbnailsInput = new();
    private readonly CheckBox visualSearchInput = new();
    private readonly Button runButton = new();
    private readonly Button openGalleryButton = new();
    private readonly RichTextBox logBox = new();
    private Process? runningProcess;

    public MainForm()
    {
        Text = "roblox thumbnail scraper";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(760, 560);
        Size = new Size(900, 680);
        Font = new Font("Segoe UI", 10F);

        scraperPath.Text = FindScraper();
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
        runButton.Text = "Run scraper";
        runButton.AutoSize = true;
        runButton.Click += async (_, _) => await RunScraperAsync();
        openGalleryButton.Text = "Open gallery";
        openGalleryButton.AutoSize = true;
        openGalleryButton.Enabled = false;
        openGalleryButton.Click += (_, _) => OpenGallery();
        logBox.ReadOnly = true;
        logBox.BackColor = Color.FromArgb(30, 30, 30);
        logBox.ForeColor = Color.Gainsboro;
        logBox.Dock = DockStyle.Fill;

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(18),
            ColumnCount = 3,
            RowCount = 8,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        AddRow(layout, 0, "Scraper EXE", scraperPath, CreateBrowseButton(BrowseScraper));
        AddRow(layout, 1, "Output folder", outputPath, CreateBrowseButton(BrowseOutput));
        AddRow(layout, 2, "Games to scrape", limitInput, new Label());
        AddRow(layout, 3, "Workers", workersInput, new Label());
        AddRow(layout, 4, "Thumbnails per game", thumbnailsInput, new Label());
        layout.Controls.Add(visualSearchInput, 1, 5);
        layout.SetColumnSpan(visualSearchInput, 2);

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight };
        buttons.Controls.Add(runButton);
        buttons.Controls.Add(openGalleryButton);
        layout.Controls.Add(buttons, 1, 6);
        layout.SetColumnSpan(buttons, 2);
        layout.Controls.Add(logBox, 0, 7);
        layout.SetColumnSpan(logBox, 3);
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

    private static Button CreateBrowseButton(EventHandler handler)
    {
        var button = new Button { Text = "Browse...", AutoSize = true };
        button.Click += handler;
        return button;
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
        logBox.Clear();
        openGalleryButton.Enabled = false;
        runButton.Enabled = false;
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

        process.OutputDataReceived += (_, args) => AppendLog(args.Data);
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
            openGalleryButton.Enabled = File.Exists(Path.Combine(destination, "index.html"));
        }
        catch (Exception exception)
        {
            AppendLog(exception.Message);
            MessageBox.Show(this, exception.Message, "Launcher error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            process.Dispose();
            runningProcess = null;
            runButton.Enabled = true;
        }
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
        var gallery = Path.Combine(outputPath.Text.Trim(), "index.html");
        if (!File.Exists(gallery))
        {
            MessageBox.Show(this, "Run the scraper first.", "Gallery not found", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        Process.Start(new ProcessStartInfo { FileName = gallery, UseShellExecute = true });
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
}
