import { withAuth } from "next-auth/middleware";

export default withAuth({
  pages: {
    signIn: "/login",
  },
});

export const config = {
  matcher: [
    /*
     * Match all request paths EXCEPT:
     * - /login, /signup (auth pages)
     * - /api/auth/* (NextAuth endpoints)
     * - /_next/static, /_next/image, /favicon.ico (Next.js internals)
     */
    "/((?!login|signup|api/auth|_next/static|_next/image|favicon\\.ico|$).*)",
  ],
};
