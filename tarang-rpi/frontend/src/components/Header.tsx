import { Bell, Search, UserCircle } from "lucide-react";

export function Header() {
  return (
    <header className="h-16 bg-background/80 backdrop-blur-md border-b border-border flex items-center justify-between px-8 sticky top-0 z-10">
      <div className="flex items-center bg-card border border-border rounded-full px-4 py-2 w-96 focus-within:border-primary/50 transition-colors">
        <Search className="w-4 h-4 text-foreground/50 mr-2" />
        <input 
          type="text" 
          placeholder="Search patients, records..." 
          className="bg-transparent border-none outline-none text-sm text-foreground w-full placeholder:text-foreground/40"
        />
      </div>

      <div className="flex items-center space-x-6">
        <button className="relative text-foreground/70 hover:text-foreground transition-colors">
          <Bell className="w-5 h-5" />
          <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-destructive rounded-full border-2 border-background"></span>
        </button>
        <div className="flex items-center space-x-3 border-l border-border pl-6">
          <div className="text-right hidden md:block">
            <p className="text-sm font-medium text-foreground">Dr. Sarah Connor</p>
            <p className="text-xs text-foreground/60">Cardiologist</p>
          </div>
          <UserCircle className="w-8 h-8 text-primary" />
        </div>
      </div>
    </header>
  );
}
