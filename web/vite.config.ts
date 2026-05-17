import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const devApiProxy = process.env.VITE_DEV_API_PROXY ?? "http://127.0.0.1:8000";
const devInDocker = Boolean(process.env.VITE_DEV_API_PROXY);

export default defineConfig({
  plugins: [react()],
  server: {
    host: devInDocker,
    port: 5173,
    proxy: {
      "/api": {
        target: devApiProxy,
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
