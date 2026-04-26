using Microsoft.EntityFrameworkCore;
using MyProject.Data;
using MyProject.Models;

var builder = WebApplication.CreateBuilder(args);

// 1. إخبار السيرفر باستخدام SQLite وملف اسمه production.db
builder.Services.AddDbContext<ApplicationDbContext>(options =>
    options.UseSqlite("Data Source=production.db"));

var app = builder.Build();

// 2. كود تلقائي لإنشاء ملف الداتا بيز أول ما السيرفر يشتغل
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
    db.Database.EnsureCreated();
}

// 3. تعديل الـ POST لاستقبال البيانات وحفظها في الداتا بيز
app.MapPost("/api/products", async (ProductResult result, ApplicationDbContext db) => 
{
    db.Products.Add(result);
    await db.SaveChangesAsync(); // هنا البيانات بتتحفظ في الملف فعلياً
    
    Console.WriteLine($"[DB SAVE] {result.Status} saved to production.db");
    return Results.Ok(new { message = "Data saved to Database!" });
});

// 4. Update the GET endpoint to explicitly state the type
app.MapGet("/api/products", async (ApplicationDbContext db) => 
{
    // Specify the type <ProductResult> before ToListAsync
    return await db.Products.ToListAsync<ProductResult>();
});

app.Run();