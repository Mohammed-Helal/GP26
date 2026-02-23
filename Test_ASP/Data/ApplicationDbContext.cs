using Microsoft.EntityFrameworkCore;
using MyProject.Models;

namespace MyProject.Data;

public class ApplicationDbContext : DbContext
{
    public ApplicationDbContext(DbContextOptions<ApplicationDbContext> options) 
        : base(options) { }

    // ده الجدول اللي هيتخزن فيه بيانات المنتجات
    public DbSet<ProductResult> Products => Set<ProductResult>();
}