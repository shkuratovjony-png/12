import React from "react";
import {createRoot} from "react-dom/client";
import {Premium} from "./Premium";
import "./reset.css";
const root=document.getElementById("root");
if(root)createRoot(root).render(<Premium/>);
