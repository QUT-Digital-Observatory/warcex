import typer
from pyfiglet import Figlet
from typing import Optional
from warcex import __version__
from warcex.plugmanager import PluginManager
from os import path, getcwd
from colorama import Fore, Back, Style, just_fix_windows_console

just_fix_windows_console()

app = typer.Typer()

def print_banner():
    """Print the custom banner with version"""
    f = Figlet(font="4max")
    lines = f.renderText("WARCex").split("\n")
    lines[-2] += f" \033[32m{__version__}\033[0m"
    typer.echo("\n".join(lines))

# Custom callback for overriding help
def custom_callback(ctx: typer.Context, param: typer.CallbackParam, value: bool):
    if not value or ctx.resilient_parsing:
        return value
    print_banner()
    typer.echo(ctx.get_help())
    ctx.exit()

@app.command()
def extract(input_file: str, output_file: str):
    """Extract contents from a WARC file to the specified output file."""
    typer.echo(f"Extracting {input_file} to {output_file}")

@app.command()
def plugins():
    """List supported data extraction plugins."""
    output_dir = path.abspath(getcwd())
    manager = PluginManager(output_dir)
    typer.echo(f"{Style.BRIGHT}{Fore.CYAN}Available plugins:")
    for i, plugin in enumerate(manager.plugins):
        info = plugin.get_info()
        typer.echo(f"{Fore.YELLOW}{i+1}. {Fore.GREEN}{info.name} (v{info.version}){Style.RESET_ALL}: {info.description}")

@app.command(name="info", help="Get information about a specific plugin by number or name.")
def plugin_info(plugin_name: str):
    """Get information about a specific plugin."""
    output_dir = path.abspath(getcwd())
    manager = PluginManager(output_dir)
    
    # Handle empty plugin list first
    if not manager.plugins:
        typer.echo(f"{Fore.RED}No plugins are currently installed.")
        return
    
    plugin = None
    # Try to interpret input as a number
    try:
        plugin_number = int(plugin_name)
        # Check if the number is within valid range
        if 1 <= plugin_number <= len(manager.plugins):
            plugin = manager.plugins[plugin_number-1]
        else:
            typer.echo(f"{Fore.RED}Invalid plugin number. Please enter a number between 1 and {len(manager.plugins)}.{Style.RESET_ALL}")
            return
    except ValueError:
        # If not a number, search by name (case-insensitive for better UX)
        plugin = next((p for p in manager.plugins if p.get_info().name.lower() == plugin_name.lower()), None)
        
        # If not found by exact name, try to find a plugin that contains the name string
        if plugin is None:
            plugin = next((p for p in manager.plugins if plugin_name.lower() in p.get_info().name.lower()), None)
            
            # If found by partial match, inform the user
            if plugin:
                plugin_info = plugin.get_info()
                typer.echo(f"{Fore.YELLOW}Found plugin with similar name: {plugin_info.name}{Style.RESET_ALL}")
                
    
    # Display plugin info if found
    if plugin is None:
        suggestions = ", ".join([f"{Fore.CYAN}{i+1}{Fore.RESET}: {p.get_info().name}" 
                               for i, p in enumerate(manager.plugins[:5])])
        typer.echo(f"{Fore.RED}Plugin '{plugin_name}' not found. Available plugins include:{Style.RESET_ALL}")
        typer.echo(suggestions + (f"{Fore.YELLOW} and {len(manager.plugins)-5} more...{Style.RESET_ALL}" 
                                if len(manager.plugins) > 5 else ""))
        return
    
    # Display the plugin information
    info = plugin.get_info()
    typer.echo(f"{Fore.GREEN}{info.name} (v{info.version}){Style.RESET_ALL}: {info.description}")
    typer.echo(f"{Fore.CYAN}Instructions:{Style.RESET_ALL} {info.instructions}")
    typer.echo(f"{Fore.CYAN}Outputs: {Fore.YELLOW}{', '.join(info.output_data)}{Style.RESET_ALL}")

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    help: Optional[bool] = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_flag=True,
        callback=custom_callback,
        is_eager=True,
    ),
    version: Optional[bool] = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        is_flag=True,
        is_eager=True,
    ),
):
    """WARCex - A tool for extracting contents from WARC files."""
    if version:
        typer.echo(f"WARCex version: {__version__}")
        raise typer.Exit()
    
    if ctx.invoked_subcommand is None:
        print_banner()
        typer.echo(ctx.get_help())
        raise typer.Exit()

def run_main():
    """This is our entry point function from poetry"""
    app()

if __name__ == "__main__":
    """If we envoke python -m warcex.cli"""
    run_main()
