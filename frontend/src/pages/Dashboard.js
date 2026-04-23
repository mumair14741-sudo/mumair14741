import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { MousePointerClick, TrendingUp, DollarSign, Users } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const COLORS = ['#3B82F6', '#22C55E', '#F59E0B', '#EF4444', '#A855F7'];

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get(`${API}/dashboard/stats`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setStats(response.data);
    } catch (error) {
      console.error("Error fetching stats:", error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-muted-foreground">Loading dashboard...</div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-muted-foreground">No data available</div>
      </div>
    );
  }

  const statCards = [
    {
      title: "Total Clicks",
      value: stats.total_clicks.toLocaleString(),
      icon: MousePointerClick,
      color: "#3B82F6",
      testid: "stat-total-clicks"
    },
    {
      title: "Unique Clicks",
      value: stats.unique_clicks.toLocaleString(),
      icon: Users,
      color: "#22C55E",
      testid: "stat-unique-clicks"
    },
    {
      title: "Conversions",
      value: stats.total_conversions.toLocaleString(),
      icon: TrendingUp,
      color: "#F59E0B",
      testid: "stat-conversions"
    },
    {
      title: "Revenue",
      value: `$${stats.revenue.toLocaleString()}`,
      icon: DollarSign,
      color: "#22C55E",
      testid: "stat-revenue"
    },
  ];

  const deviceData = stats.clicks_by_device.map(item => ({
    name: item.device.charAt(0).toUpperCase() + item.device.slice(1),
    value: item.count
  }));

  return (
    <div className="space-y-6" data-testid="dashboard">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((stat, index) => {
          const Icon = stat.icon;
          return (
            <Card key={index} className="stat-card bg-[#09090B] border-[#27272A]" data-testid={stat.testid}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {stat.title}
                </CardTitle>
                <div
                  className="w-10 h-10 rounded-md flex items-center justify-center"
                  style={{ backgroundColor: `${stat.color}20` }}
                >
                  <Icon size={20} style={{ color: stat.color }} />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold font-mono">{stat.value}</div>
                {stat.title === "Conversions" && (
                  <p className="text-xs text-muted-foreground mt-1">
                    {stats.conversion_rate}% conversion rate
                  </p>
                )}
                {stat.title === "Revenue" && (
                  <p className="text-xs text-muted-foreground mt-1">
                    ${stats.epc} EPC
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-[#09090B] border-[#27272A]" data-testid="clicks-chart">
          <CardHeader>
            <CardTitle className="text-lg">Clicks Over Time</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={stats.clicks_by_date}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272A" />
                <XAxis dataKey="date" stroke="#A1A1AA" style={{ fontSize: 12 }} />
                <YAxis stroke="#A1A1AA" style={{ fontSize: 12 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#18181B',
                    border: '1px solid #27272A',
                    borderRadius: '6px',
                    color: '#FAFAFA'
                  }}
                />
                <Line type="monotone" dataKey="count" stroke="#3B82F6" strokeWidth={2} dot={{ fill: '#3B82F6' }} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="bg-[#09090B] border-[#27272A]" data-testid="revenue-chart">
          <CardHeader>
            <CardTitle className="text-lg">Revenue Over Time</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={stats.revenue_by_date}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272A" />
                <XAxis dataKey="date" stroke="#A1A1AA" style={{ fontSize: 12 }} />
                <YAxis stroke="#A1A1AA" style={{ fontSize: 12 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#18181B',
                    border: '1px solid #27272A',
                    borderRadius: '6px',
                    color: '#FAFAFA'
                  }}
                />
                <Line type="monotone" dataKey="revenue" stroke="#22C55E" strokeWidth={2} dot={{ fill: '#22C55E' }} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-[#09090B] border-[#27272A]" data-testid="country-chart">
          <CardHeader>
            <CardTitle className="text-lg">Top Countries</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stats.clicks_by_country}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272A" />
                <XAxis dataKey="country" stroke="#A1A1AA" style={{ fontSize: 12 }} />
                <YAxis stroke="#A1A1AA" style={{ fontSize: 12 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#18181B',
                    border: '1px solid #27272A',
                    borderRadius: '6px',
                    color: '#FAFAFA'
                  }}
                />
                <Bar dataKey="count" fill="#3B82F6" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="bg-[#09090B] border-[#27272A]" data-testid="device-chart">
          <CardHeader>
            <CardTitle className="text-lg">Device Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={deviceData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  outerRadius={100}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {deviceData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#18181B',
                    border: '1px solid #27272A',
                    borderRadius: '6px',
                    color: '#FAFAFA'
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
