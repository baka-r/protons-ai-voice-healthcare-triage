import { ChakraProvider } from "@chakra-ui/react";
import "@fontsource-variable/inter";
import "@fontsource/instrument-serif/400.css";
import "@fontsource/instrument-serif/400-italic.css";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { system } from "./theme";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ChakraProvider value={system}>
      <App />
    </ChakraProvider>
  </React.StrictMode>,
);
