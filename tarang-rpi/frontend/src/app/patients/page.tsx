import { UserPlus, MoreVertical, Activity } from "lucide-react";

export default function Patients() {
  const patients = [
    { id: "P-1042", name: "John Doe", age: 45, status: "Critical", lastSync: "2 mins ago" },
    { id: "P-1043", name: "Jane Smith", age: 62, status: "Stable", lastSync: "10 mins ago" },
    { id: "P-1044", name: "Alice Johnson", age: 28, status: "Monitoring", lastSync: "1 hr ago" },
    { id: "P-1045", name: "Robert Brown", age: 71, status: "Stable", lastSync: "4 hrs ago" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-foreground">Patients</h1>
          <p className="text-foreground/60 mt-1">Manage and monitor patient list</p>
        </div>
        <button className="bg-primary hover:bg-primary/90 text-primary-foreground px-4 py-2 rounded-xl flex items-center transition-colors font-medium shadow-[0_0_15px_rgba(59,130,246,0.3)]">
          <UserPlus className="w-4 h-4 mr-2" />
          Add Patient
        </button>
      </div>

      <div className="bg-card border border-border rounded-2xl overflow-hidden shadow-sm">
        <table className="w-full text-left">
          <thead className="bg-secondary/50 border-b border-border">
            <tr>
              <th className="py-4 px-6 font-medium text-foreground/70 text-sm">Patient ID</th>
              <th className="py-4 px-6 font-medium text-foreground/70 text-sm">Name</th>
              <th className="py-4 px-6 font-medium text-foreground/70 text-sm">Age</th>
              <th className="py-4 px-6 font-medium text-foreground/70 text-sm">Status</th>
              <th className="py-4 px-6 font-medium text-foreground/70 text-sm">Last Sync</th>
              <th className="py-4 px-6 font-medium text-foreground/70 text-sm text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {patients.map((p) => (
              <tr key={p.id} className="hover:bg-secondary/20 transition-colors group cursor-pointer">
                <td className="py-4 px-6 font-mono text-sm text-foreground/80">{p.id}</td>
                <td className="py-4 px-6 font-medium text-foreground flex items-center">
                  <div className="w-8 h-8 rounded-full bg-primary/20 text-primary flex items-center justify-center mr-3 text-xs font-bold border border-primary/30">
                    {p.name.charAt(0)}
                  </div>
                  {p.name}
                </td>
                <td className="py-4 px-6 text-foreground/80 text-sm">{p.age}</td>
                <td className="py-4 px-6">
                  <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border
                    ${p.status === 'Critical' ? 'bg-destructive/10 text-destructive border-destructive/20 shadow-[0_0_10px_rgba(239,68,68,0.2)]' : 
                      p.status === 'Monitoring' ? 'bg-warning/10 text-warning border-warning/20 shadow-[0_0_10px_rgba(245,158,11,0.2)]' : 
                      'bg-success/10 text-success border-success/20 shadow-[0_0_10px_rgba(16,185,129,0.2)]'}`}>
                    {p.status}
                  </span>
                </td>
                <td className="py-4 px-6 text-sm text-foreground/60 flex items-center">
                  <Activity className="w-3 h-3 mr-2 text-foreground/40" />
                  {p.lastSync}
                </td>
                <td className="py-4 px-6 text-right">
                  <button className="text-foreground/50 hover:text-foreground transition-colors p-2 rounded-lg hover:bg-secondary">
                    <MoreVertical className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
