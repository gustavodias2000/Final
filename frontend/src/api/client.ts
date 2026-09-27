import axios from "axios";

// Em desenvolvimento, o Vite encaminha /api para o backend local. Em produção,
// VITE_API_BASE_URL continua permitindo apontar para a API publicada.
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 90_000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && localStorage.getItem("token")) {
      localStorage.removeItem("token");
      window.location.reload();
    }
    return Promise.reject(error);
  },
);

export default api;
