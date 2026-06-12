import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Transform JSX and enable React's development refresh behavior.
  plugins: [react()],
  server: {
    // Keep the development URL consistent with the production container.
    port: 3000,
    proxy: {
      // During development Express runs separately on port 3001.
      "/api": "http://localhost:3001"
    }
  }
});
