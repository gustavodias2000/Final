import { useAuth } from "./auth/AuthContext";
import Login from "./auth/Login";
import Dashboard from "./pages/Dashboard";

export default function App() {
  const { token } = useAuth();
  return token ? <Dashboard /> : <Login />;
}
