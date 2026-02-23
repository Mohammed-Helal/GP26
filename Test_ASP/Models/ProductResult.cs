namespace MyProject.Models;

public class ProductResult
{
    public int Id { get; set; }
    public string Status { get; set; } = string.Empty;
    public double Confidence { get; set; }
    public DateTime Timestamp { get; set; } = DateTime.Now;
} 