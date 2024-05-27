import dynamic from "next/dynamic";
import { Suspense } from "react";

const Editor = dynamic(() => import("./Editor"), { ssr: false });


export default function Home() {
  return (
    <Suspense fallback="Loading...">
      <Editor />
    </Suspense>
  )
}
