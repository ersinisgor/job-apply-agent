# PROJECTS LIST (detailed)

IMPORTANT FOR CV GENERATION:
- Only use the technologies/details listed here when adding or modifying a CV project.
- When you add a project to the CV, render its title as a Markdown link to its GitHub URL:
  `#### [Project Title](GITHUB_URL)`. Do not invent URLs; use the **GitHub** field below.
- If a project has no GitHub URL, keep the title as plain text.

---

## 1. API Hotel Project
- **GitHub:** https://github.com/ersinisgor/ApiHotelProject
- **Local:** /Users/mac/Desktop/Sağ Orta Üst/APIHotelProject-.NET
- **Summary:** Comprehensive hotel management system (ASP.NET Core API + MS SQL Server) for hotel admins and guests, with auth, booking management, and external API integration.
- **Tech:** ASP.NET Core API, ASP.NET MVC, Entity Framework Core, MS SQL Server, ASP.NET Identity, JWT, AutoMapper, FluentValidation, Swagger (Swashbuckle), Rapid API (API consume), NETCore.MailKit (SMTP), Bootstrap 5, OOP.
- **Key features:** JWT auth & authorization; booking/room/staff/service/testimonial management; external Rapid API integration (hotel booking, exchange rate); separate Admin and guest (Default) interfaces; file/photo upload; reusable View Components.
- **Architecture:** N-tier layered architecture (Entity, Data Access, DTO, Business, Web API layers) + MVC frontend; Repository Design Pattern; EF Core DbContext; AutoMapper DTO↔entity mapping; FluentValidation.

## 2. Movie App MERN (Movie Streaming Platform)
- **GitHub:** https://github.com/ersinisgor/movie_app_MERN
- **Local:** /Users/mac/code/ersinisgor/movie_app_MERN
- **Summary:** Full-stack movie/TV streaming platform where authenticated users browse, search, and watch trailers with a persistent search history.
- **Tech (frontend):** React 18, Vite, React Router, Zustand, Axios, React Player, React Hot Toast, Lucide React, Tailwind CSS. **(backend):** Node.js, Express, MongoDB, Mongoose, JWT (jsonwebtoken), bcryptjs, cookie-parser, dotenv.
- **Key features:** JWT auth (signup/login); browse trending/top-rated/upcoming movies & TV; search movies, TV, and actors; embedded trailers + detail pages; search-history tracking (delete/clear); fully responsive (desktop/tablet/mobile).
- **Architecture:** Modular structure (Pages/Components/Stores); JWT middleware-protected routes; separation of auth/content/search concerns; shimmer loading animations.

## 3. Personal Portfolio Website
- **GitHub:** https://github.com/ersinisgor/portfolio-nextjs
- **Local:** /Users/mac/code/ersinisgor/portfolio-ersin-nextjs
- **Summary:** High-performance, fully responsive personal portfolio built with Next.js 15 App Router and a modern animated UI.
- **Tech:** React 18, Next.js 15 (App Router), Tailwind CSS, shadcn/ui (Radix UI), framer-motion, tsparticles, embla-carousel, react-hook-form, Zod, @hookform/resolvers, Formspree (contact form), lucide-react / react-icons, Vercel deployment.
- **Key features:** animated hero/particles and carousels; responsive sections; accessible Radix/shadcn components; validated contact form (react-hook-form + Zod + Formspree); optimized performance with App Router + Client Components.
- **Architecture:** Next.js App Router with Client Components; component-library-driven UI (shadcn/Aceternity/Magic UI style); utility-first Tailwind.

## 4. Food Ordering App MERN
- **GitHub:** https://github.com/ersinisgor/food_ordering_MERN
- **Local:** /Users/mac/code/ersinisgor/food_ordering_MERN (+ food_ordering_MERN-backend)
- **Summary:** Full-stack food ordering platform — users browse restaurants and place orders; restaurant owners manage menus and incoming orders. ~97% TypeScript.
- **Tech (frontend):** TypeScript, React 18, Vite, Tailwind CSS, shadcn/ui (Radix UI), React Router, React Query, React Hook Form, Zod, Auth0 (@auth0/auth0-react), Sonner. **(backend):** TypeScript, Node.js, Express, MongoDB, Mongoose, JWT, Auth0 (express-oauth2-jwt-bearer), Multer, Cloudinary, Stripe, express-validator. **(tools):** Postman, Git, Render.
- **Key features:** restaurant discovery + dynamic menu browsing; cart & order placement with real-time order tracking; Stripe payments; user profile + order history; restaurant-owner menu & order management; Cloudinary image upload.
- **Architecture:** typed full-stack; Auth0 identity + JWT authorization; React Query server-state/caching; deployed on Render.

## 5. Hotel Booking App MERN
- **GitHub:** https://github.com/ersinisgor/hotel_booking_app_MERN
- **Local:** /Users/mac/code/ersinisgor/booking_app_MERN
- **Summary:** Full-stack hotel booking platform to search, filter, and book hotels with secure Stripe payments. ~99% TypeScript.
- **Tech (frontend):** TypeScript, React 19, Vite, Tailwind CSS v4, React Router, React Hook Form, React Query (@tanstack/react-query), Stripe (@stripe/react-stripe-js), react-datepicker. **(backend):** TypeScript, Node.js, Express, MongoDB, Mongoose, JWT, bcryptjs, cookie-parser, Multer, Cloudinary, Stripe, express-validator. **(testing):** Playwright (End-to-End).
- **Key features:** JWT auth with secure HTTP cookies; hotel management with Cloudinary image upload; advanced search/sort/filter; Stripe booking payments; booking-management dashboard; dynamic homepage of recently added hotels.
- **Architecture:** typed full-stack; React Query data fetching; E2E test suite (e2e-tests dir); deployed on Render.

## 6. NestJS Library Management System
- **GitHub:** https://github.com/ersinisgor/Nest.js-Library-Management-System
- **Local:** /Users/mac/code/ersinisgor/nestjs-library-management
- **Summary:** Backend library system (NestJS) implementing real-world borrowing rules, RBAC, and an automated fine system over a PostgreSQL database.
- **Tech:** NestJS 11, TypeScript, TypeORM, PostgreSQL (pg), JWT (@nestjs/jwt), bcrypt, class-validator, class-transformer, @nestjs/config, Guards, ValidationPipe, Jest, Supertest.
- **Key features:** borrow limit (max 3 books, 14-day term); overdue fines ($0.50/day) with auto-block over $10 unpaid; renewals (+7 days); role-based access (Admin/Member) via Guards & @Roles; full borrowing audit trail; 30+ REST endpoints (auth, books, authors, fines).
- **Architecture:** modular NestJS (controller→service→data); JWT auth with env-configured expiry; AuthGuard + role decorators; service-layer business logic (fine calc, limit validation); global ValidationPipe + class-validator DTOs.

## 7. .NET Cloud File Storage Microservice
- **GitHub:** https://github.com/ersinisgor/.NET-Cloud-File-Storage-Microservice
- **Local:** (not provided)
- **Summary:** Microservices-based cloud file storage system with secure auth, file management, flexible sharing, and a centralized API Gateway.
- **Tech:** ASP.NET Core, Entity Framework Core, MediatR (CQRS), AutoMapper, FluentValidation, JWT, BCrypt, PostgreSQL, SQLite, YARP (reverse-proxy Gateway), ASP.NET Core MVC, Bootstrap.
- **Key features:** JWT auth validated across services; file upload/list/download/delete; three-tier sharing (private/public/specific users); centralized Gateway routing with auth enforcement; MVC dashboard; RBAC (read/edit).
- **Architecture (microservices):** Authentication API (SQLite), File Metadata API (PostgreSQL), File Storage API (filesystem), Gateway API (YARP), MVC frontend; CQRS via MediatR.

## 8. NestJS English Vocabulary Trainer
- **GitHub:** https://github.com/ersinisgor/English_Vocabulary_Trainer
- **Local:** /Users/mac/code/ersinisgor/English_Vocabulary_Trainer
- **Summary:** Full-stack vocabulary learning platform (NestJS backend + Next.js frontend) — a customizable learning engine with SRS-like scheduling, multiple exercise types, and performance analytics.
- **Tech (backend):** NestJS 11, TypeScript, Prisma ORM, PostgreSQL (pg), JWT (@nestjs/jwt), Passport (passport-jwt/local), bcrypt, class-validator, Joi, Multer, xlsx (SheetJS) Excel import, Swagger (@nestjs/swagger), Jest. **(frontend):** Next.js 16, React 19, Tailwind CSS v4, Zustand, Axios, React Hook Form, Zod.
- **Key features:** algorithm-driven (SRS-like) scheduling with per-word stats; multi-type exercises (flash cards, multiple choice, sentence, writing) with dynamic filtering; Excel bulk import; user-scoped word/folder management & multi-language; performance analytics (asked/correct/incorrect, weekly frequency); composable query filters.
- **Architecture:** modular feature-based structure (controller→service→data); JWT-protected, user-scoped data isolation; transaction-based pagination; Prisma migrations/seeding; Swagger docs; Jest unit/E2E.

## 9. AI Gift Advisor
- **GitHub:** https://github.com/ersinisgor/AI-Gift-Advisor
- **Local:** /Users/mac/code/ersinisgor/AI-Gift-Advisor
- **Summary:** Full-stack AI web app that generates personalized gift suggestions from a user's description using the OpenAI GPT model, with streamed responses.
- **Tech (backend):** Node.js, Express 5, OpenAI API, streaming responses, CORS, dotenv. **(frontend):** React 19, Vite, Axios, Marked (Markdown rendering), DOMPurify (XSS-safe).
- **Key features:** AI gift-recommendation engine; real-time streaming responses; safe Markdown rendering (Marked + DOMPurify); env-based API key management; clean responsive UI; production-deploy ready (Render).
- **Architecture:** separated frontend/backend; Express server proxies OpenAI with streaming; environment-based secret handling.

## 10. AI Knowledge Base Assistant (Full-Stack RAG Platform)
- **GitHub:** https://github.com/ersinisgor/AI-Knowledge-Base-Assistant
- **Local:** /Users/mac/code/ersinisgor/AI-Knowledge-Base-Assistant
- **Summary:** Production-grade full-stack RAG platform (monorepo) for document ingestion, vector search, and AI-powered Q&A with source attribution.
- **Tech (backend):** NestJS 11, TypeScript, OpenAI API (GPT-4o-mini + text-embedding-3-small), LangChain (RecursiveCharacterTextSplitter), Supabase PostgreSQL + pgvector (HNSW), Multer, pdf-parse, provider interfaces (ILLMProvider/IEmbeddingProvider). **(frontend):** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui, Recharts.
- **Key features:** end-to-end RAG (query rewriting → vector retrieval → confidence-aware generation); pgvector HNSW semantic search; retrieval confidence scoring (HIGH/MEDIUM/LOW); token-budgeted context assembly; source attribution/citations with similarity scores; real-time metrics dashboard (latency, indexed docs, activity).
- **Architecture:** 5-step ingestion + 9-step RAG pipelines; swappable AI provider interfaces; custom `match_documents()` RPC (cosine similarity); Next.js API routes proxy backend (no CORS, server-side backend URL); 500-char chunks / 80-char overlap, 1536-dim embeddings.
