import axios from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE, // http://127.0.0.1:8010
  timeout: 15000,
  withCredentials: false,
  headers: { "X-User": "Roy Mathew" },
});

api.interceptors.response.use(
  r => r,
  err => {
    // Helpful console error instead of vague overlay
    console.error("API error:", {
      url: err?.config?.url,
      params: err?.config?.params,
      message: err?.message,
      status: err?.response?.status,
      data: err?.response?.data,
    });
    return Promise.reject(err);
  }
);
