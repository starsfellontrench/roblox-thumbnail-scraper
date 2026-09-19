namespace RobloxThumbnailGallery;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var folder = args.Length > 0 && Directory.Exists(args[0]) ? args[0] : ChooseFolder();
        if (string.IsNullOrWhiteSpace(folder))
        {
            return;
        }
        Application.Run(new MainForm(folder));
    }

    private static string ChooseFolder()
    {
        using var dialog = new FolderBrowserDialog { Description = "Choose a scraper output folder" };
        return dialog.ShowDialog() == DialogResult.OK ? dialog.SelectedPath : string.Empty;
    }
}
