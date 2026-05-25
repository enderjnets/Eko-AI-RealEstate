import { redirect } from "next/navigation";

// Root → dashboard. The public-facing landing placeholder lives at /about.
export default function Home() {
  redirect("/leads");
}
