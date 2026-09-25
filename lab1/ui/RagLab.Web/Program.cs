using Microsoft.AspNetCore.Components.Web;
using Microsoft.AspNetCore.Components.WebAssembly.Hosting;
using RagLab.Web;
using RagLab.Web.Services;

// Blazor WebAssembly: .NET-код выполняется в браузере. Собранное приложение
// раздаёт тот же FastAPI (src/api/app.py), поэтому API — на том же адресе.
var builder = WebAssemblyHostBuilder.CreateDefault(args);
builder.RootComponents.Add<App>("#app");
builder.RootComponents.Add<HeadOutlet>("head::after");

// RagApi:BaseUrl (wwwroot/appsettings.json) пустой → тот же origin, что и страница
var apiBase = builder.Configuration["RagApi:BaseUrl"];
builder.Services.AddScoped(_ => new RagApiClient(new HttpClient
{
    BaseAddress = new Uri(string.IsNullOrWhiteSpace(apiBase) ? builder.HostEnvironment.BaseAddress : apiBase),
    Timeout = TimeSpan.FromMinutes(3),
}));

await builder.Build().RunAsync();
