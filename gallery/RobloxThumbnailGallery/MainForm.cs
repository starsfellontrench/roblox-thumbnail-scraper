using System.Diagnostics;
using System.Text.Json;

namespace RobloxThumbnailGallery;

public sealed class MainForm : Form
{
    private readonly string outputDirectory;
    private readonly TextBox searchInput = new();
    private readonly ComboBox sortInput = new();
    private readonly CheckBox favoritesOnly = new();
    private readonly Label resultLabel = new();
    private readonly FlowLayoutPanel cards = new();
    private readonly HashSet<string> favorites = new(StringComparer.OrdinalIgnoreCase);
    private List<GameRecord> games = new();

    public MainForm(string folder)
    {
        outputDirectory = Path.GetFullPath(folder);
        Text = "Roblox Thumbnail Gallery";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(900, 650);
        Size = new Size(1280, 850);
        BackColor = Color.FromArgb(24, 24, 24);
        ForeColor = Color.Gainsboro;
        Font = new Font("Segoe UI", 10F);
        BuildLayout();
        LoadData();
    }

    private void BuildLayout()
    {
        var root = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1, Padding = new Padding(12), BackColor = BackColor };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var toolbar = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, WrapContents = false, AutoScroll = true };
        var chooseButton = new Button { Text = "Choose folder", AutoSize = true };
        chooseButton.Click += (_, _) => ChooseFolder();
        searchInput.Width = 260;
        searchInput.PlaceholderText = "Search games, tags, or descriptions";
        searchInput.TextChanged += (_, _) => RenderCards();
        sortInput.Width = 140;
        sortInput.DropDownStyle = ComboBoxStyle.DropDownList;
        sortInput.Items.AddRange(new object[] { "Rank", "Name", "Players" });
        sortInput.SelectedIndex = 0;
        sortInput.SelectedIndexChanged += (_, _) => RenderCards();
        favoritesOnly.Text = "Favorites only";
        favoritesOnly.AutoSize = true;
        favoritesOnly.CheckedChanged += (_, _) => RenderCards();
        var refreshButton = new Button { Text = "Refresh", AutoSize = true };
        refreshButton.Click += (_, _) => LoadData();
        resultLabel.AutoSize = true;
        resultLabel.Margin = new Padding(12, 9, 0, 0);
        toolbar.Controls.Add(chooseButton);
        toolbar.Controls.Add(searchInput);
        toolbar.Controls.Add(sortInput);
        toolbar.Controls.Add(favoritesOnly);
        toolbar.Controls.Add(refreshButton);
        toolbar.Controls.Add(resultLabel);

        cards.Dock = DockStyle.Fill;
        cards.AutoScroll = true;
        cards.WrapContents = true;
        cards.FlowDirection = FlowDirection.LeftToRight;
        cards.Padding = new Padding(4);
        cards.BackColor = Color.FromArgb(18, 18, 18);
        root.Controls.Add(toolbar, 0, 0);
        root.Controls.Add(cards, 0, 1);
        Controls.Add(root);
    }

    private void ChooseFolder()
    {
        using var dialog = new FolderBrowserDialog { SelectedPath = outputDirectory, Description = "Choose a scraper output folder" };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            Process.Start(new ProcessStartInfo { FileName = Application.ExecutablePath, ArgumentList = { dialog.SelectedPath }, UseShellExecute = true });
            Close();
        }
    }

    private void LoadData()
    {
        var file = Path.Combine(outputDirectory, "games.json");
        if (!File.Exists(file))
        {
            resultLabel.Text = "games.json was not found";
            cards.Controls.Clear();
            return;
        }
        try
        {
            games = JsonSerializer.Deserialize<List<GameRecord>>(File.ReadAllText(file), new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? new List<GameRecord>();
            LoadFavorites();
            RenderCards();
        }
        catch (Exception exception)
        {
            resultLabel.Text = exception.Message;
        }
    }

    private void LoadFavorites()
    {
        favorites.Clear();
        var file = Path.Combine(outputDirectory, "favorites.json");
        if (!File.Exists(file))
        {
            return;
        }
        try
        {
            var values = JsonSerializer.Deserialize<List<string>>(File.ReadAllText(file)) ?? new List<string>();
            foreach (var value in values)
            {
                favorites.Add(value);
            }
        }
        catch
        {
        }
    }

    private void SaveFavorites()
    {
        File.WriteAllText(Path.Combine(outputDirectory, "favorites.json"), JsonSerializer.Serialize(favorites.Order(StringComparer.OrdinalIgnoreCase).ToList(), new JsonSerializerOptions { WriteIndented = true }));
    }

    private void RenderCards()
    {
        cards.SuspendLayout();
        cards.Controls.Clear();
        var query = searchInput.Text.Trim();
        var filtered = games.Where(game => Matches(game, query)).ToList();
        filtered = sortInput.SelectedItem?.ToString() switch
        {
            "Name" => filtered.OrderBy(game => game.Name).ThenBy(game => game.Rank).ToList(),
            "Players" => filtered.OrderByDescending(game => game.Players).ThenBy(game => game.Rank).ToList(),
            _ => filtered.OrderBy(game => game.Rank).ToList(),
        };
        foreach (var game in filtered)
        {
            foreach (var thumbnail in game.ThumbnailFiles.Select((path, index) => new { path, index }))
            {
                var key = thumbnail.path.Replace('\\', '/');
                if (favoritesOnly.Checked && !favorites.Contains(key))
                {
                    continue;
                }
                cards.Controls.Add(CreateCard(game, thumbnail.path, thumbnail.index, key));
            }
        }
        resultLabel.Text = $"{cards.Controls.Count} thumbnails from {filtered.Count} games";
        cards.ResumeLayout();
    }

    private bool Matches(GameRecord game, string query)
    {
        if (favoritesOnly.Checked && !game.ThumbnailFiles.Any(path => favorites.Contains(path.Replace('\\', '/'))))
        {
            return false;
        }
        if (string.IsNullOrWhiteSpace(query))
        {
            return true;
        }
        var searchable = string.Join(" ", new[] { game.Name, game.Description }.Concat(game.ThumbnailTags.SelectMany(tags => tags)));
        return searchable.Contains(query, StringComparison.OrdinalIgnoreCase);
    }

    private Control CreateCard(GameRecord game, string relativePath, int index, string key)
    {
        var card = new Panel { Width = 350, Height = 310, Margin = new Padding(8), BackColor = Color.FromArgb(42, 42, 42), Padding = new Padding(8) };
        var image = new PictureBox { Width = 334, Height = 188, SizeMode = PictureBoxSizeMode.Zoom, BackColor = Color.FromArgb(28, 28, 28), Cursor = Cursors.Hand };
        var fullPath = Path.Combine(outputDirectory, relativePath);
        if (File.Exists(fullPath))
        {
            image.Image = LoadDetachedImage(fullPath);
        }
        image.Click += (_, _) => ShowPreview(fullPath, $"{game.Name} thumbnail {index + 1}");
        var title = new Label { Text = game.Name, AutoEllipsis = true, AutoSize = false, Width = 334, Height = 24, ForeColor = Color.DeepSkyBlue, Location = new Point(8, 202) };
        var meta = new Label { Text = $"#{game.Rank}  {image.Image?.Width ?? 0}x{image.Image?.Height ?? 0}  {game.Players:N0} players", AutoEllipsis = true, AutoSize = false, Width = 334, Height = 22, Location = new Point(8, 226), ForeColor = Color.LightGray };
        var tags = index < game.ThumbnailTags.Count ? string.Join(", ", game.ThumbnailTags[index].Take(4)) : string.Empty;
        var tagLabel = new Label { Text = tags, AutoEllipsis = true, AutoSize = false, Width = 334, Height = 20, Location = new Point(8, 248), ForeColor = Color.DarkGray };
        var actions = new FlowLayoutPanel { Location = new Point(8, 270), Width = 334, Height = 32, WrapContents = false };
        var favorite = new Button { Text = favorites.Contains(key) ? "Unfavorite" : "Favorite", AutoSize = true };
        favorite.Click += (_, _) =>
        {
            if (!favorites.Add(key))
            {
                favorites.Remove(key);
            }
            SaveFavorites();
            RenderCards();
        };
        var copy = new Button { Text = "Copy path", AutoSize = true };
        copy.Click += (_, _) => Clipboard.SetText(fullPath);
        var open = new Button { Text = "Open game", AutoSize = true };
        open.Click += (_, _) => Process.Start(new ProcessStartInfo { FileName = $"https://www.roblox.com/games/{game.PlaceId}", UseShellExecute = true });
        actions.Controls.Add(favorite);
        actions.Controls.Add(copy);
        actions.Controls.Add(open);
        card.Controls.Add(image);
        card.Controls.Add(title);
        card.Controls.Add(meta);
        card.Controls.Add(tagLabel);
        card.Controls.Add(actions);
        return card;
    }

    private static Image? LoadDetachedImage(string path)
    {
        try
        {
            using var source = Image.FromFile(path);
            return new Bitmap(source);
        }
        catch
        {
            return null;
        }
    }

    private void ShowPreview(string path, string title)
    {
        if (!File.Exists(path))
        {
            return;
        }
        var preview = new Form { Text = title, StartPosition = FormStartPosition.CenterParent, Size = new Size(900, 600), BackColor = Color.Black };
        var image = new PictureBox { Dock = DockStyle.Fill, SizeMode = PictureBoxSizeMode.Zoom, Image = LoadDetachedImage(path) };
        preview.Controls.Add(image);
        preview.Show(this);
    }

    private sealed class GameRecord
    {
        public int Rank { get; set; }
        public long PlaceId { get; set; }
        public long Players { get; set; }
        public string Name { get; set; } = string.Empty;
        public string Description { get; set; } = string.Empty;
        public List<string> ThumbnailFiles { get; set; } = new();
        public List<List<string>> ThumbnailTags { get; set; } = new();
    }
}
