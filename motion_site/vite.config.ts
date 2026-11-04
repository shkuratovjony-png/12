import {defineConfig} from "vite";
export default defineConfig({
  base:"/s/m/static/",
  esbuild:{jsx:"automatic"},
  build:{
    outDir:"dist",emptyOutDir:true,cssCodeSplit:false,
    rollupOptions:{
      input:"index.html",
      output:{
        entryFileNames:"assets/motion.js",
        chunkFileNames:"assets/[name].js",
        assetFileNames:(a)=>a.name?.endsWith(".css")?"assets/motion.css":"assets/[name].[ext]"
      }
    }
  }
});
