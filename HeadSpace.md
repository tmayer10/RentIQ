# 🏠 RentIQ - AI-Powered Housing Affordability Platform

## 📋 Project Overview

**RentIQ** is an intelligent apartment search and recommendation platform designed to help recent graduates and young professionals find affordable housing in New York City. The application combines real estate data analytics with natural language AI to deliver personalized rental insights through conversational search.

### Key Contributors:
- Karanveer Lamba
- Vicky Liu
- Tom Mayer
- Scott Stossel
- Jo Zhu

### Superusers for Django
tommayer: RentSmarter


# 👷 Dev Log
#### 10/15/25: Tom

- created postgres database and tables
- imported data from json to tables
- created user `rentiq_user` with password `RentIQ2025!`


### Core Value Proposition
- **Natural Language Search**: State preferences without requiring fixed inputs like "I'm looking for a 3-bedroom in or nearby Chelsea under $7k with washer/dryer in unit. I will have three roommates, we are also open to a 2-bedroom with adding a flex wall. I slightly value a nearby subway station and off one of the main avenues" instead of filtering through endless listings without capturing variable priotities.
- **Live Market Data**: Real-time database of ~10,000+ active Manhattan rental listings
- **AI-Driven Recommendations**: RAG (Retrieval-Augmented Generation) architecture for intelligent matching based on user preferences
- **Affordability Analytics**: Market forecasting and affordability insights tailored for recent graduates

---

## 🏗️ Technical Architecture

### Stack
- **Backend**: Django + Django REST Framework
- **Database**: PostgreSQL with vector embeddings support (TBD)
- **Frontend**: React 
- **AI/ML**: OpenAI API (?), embeddings for semantic search
- **Cloud Infrastructure**: AWS (EC2 instance, RDS for relational DB, S3 (maybe), CloudFront)

### Data Pipeline
1. **Data Collection**: Web scraping from StreetEasy and Zillow
2. **Data Processing**: ETL pipeline for cleaning and normalization
3. **Embedding Generation**: Convert listing descriptions to vector embeddings
4. **Search & Retrieval**: Hybrid search (semantic + structured filters)
5. **LLM Integration**: Generate natural language responses with context

### Key Models
- **Listing**: Core apartment listing data (price, beds, baths, amenities, location)
- **Building**: Normalized building information to reduce duplication
- **SubwayStation**: Transit access data for location-based search
- **ListingSubway**: Distance mapping between listings and subway stations
- **UserSearch**: Query tracking for analytics and model improvement

---

## 🎯 Features (Planned)

### Phase 1: MVP (Current) 
#### Due Date: 10/27/25
- ✅ StreetEasy API download 
- ✅ Database schema design 
- ✅ PostgreSQL setup with ~10K Manhattan listings 
- 🔄 Data import pipeline from JSON/CSV
- 🔄 Basic REST API for listing retrieval
- 🔄 Admin panel for data management

### Phase 2: Core Search
#### Due Date: *Tentative*
- Natural language query parsing
- Vector similarity search with embeddings
- Structured filters (price, bedrooms, neighborhood, amenities)
- Hybrid ranking algorithm?? Or will the AI match with just prompts
- React frontend with search interface

### Phase 3: AI Integration
- RAG architecture with conversation memory
- Multi-turn conversations ("Show me cheaper options", "What about Tribecca instead of Chelsea?")
- Personalized recommendations based on preferences
- Price trend analysis and forecasting? (Karan's predictive model)

### Phase 4: Production & Deployment for Presentation
#### Due Date: 12/08/25
- AWS deployment (EC2 + RDS + S3)
- Saved searches and alerts

### Phase 5: *Nice to Haves Brainstorming*
- Other boroughs
-

---

## 📊 Data Sources

### Primary Dataset: StreetEasy Manhattan Listings
- **Size**: ~10,000 active listings
- **Fields**: 28+ attributes per listing
- **Location**: `/EDA/Datasets/StreetEasy/manhattan_details.json` (or csv version)
- **Includes**: Price, bedrooms, bathrooms, amenities, location, images, subway access

### Supporting Datasets
- **Zillow Rental Data**: Market trends and historical pricing
- **CPI Data**: Inflation adjustments for affordability analysis
- **Fair Market Rents (FMR)**: HUD data for comparative analysis
- **NYC Open Data**: Neighborhood demographics and characteristics

---

## 🚀 Deployment Strategy

### Development Environment
- Local PostgreSQL database
- Django development server
- React development server (Vite)
- `.env` file for secrets management

### Production (AWS)
- **EC2**: Django application + React build (monolithic deployment)
- **RDS PostgreSQL**: Managed database with automated backups
- **S3**: Static assets (images, CSS, JS) and media storage
- **CloudFront**: CDN for fast global delivery
- **Route 53**: Domain management
- **API Gateway** (optional): REST API exposure
- **Cognito** (optional): User authentication and management

### Security & Best Practices
- Environment-based configuration
- Secrets stored in AWS Secrets Manager
- HTTPS/SSL certificates via AWS Certificate Manager
- Database connection pooling
- Redis caching layer (future)
- Rate limiting on APIs

---

## 🎓 Target Audience

### Primary Users
- **Recent College Graduates**: First-time renters entering NYC job market
- **Young Professionals**: Early career (1-5 years) seeking better value
- **Relocating Workers**: Moving to NYC for new opportunities

### User Needs
- Budget-conscious search (student loans, entry-level salaries)
- Time-efficient apartment hunting
- Neighborhood discovery and education
- Transparent pricing and market insights
- Commute-aware recommendations

---

## 📈 Success Metrics

### Technical Metrics
#### Need some way to evaluate - check with Scott on his textbook
- Search latency < 500ms
- Database query optimization (indexed fields)
- 99.9% uptime on production
- AI response relevance score > 85%

### User Metrics
- Time to find suitable listing
- Search refinement rate
- Saved listings per user
- Conversion to viewing/application

---


---

## 🔧 Development Commands

### Backend Setup
```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Database Management
```bash
# Create PostgreSQL database
createdb rentiq_db

# Import data (custom management command)
python manage.py import_listings --file ../EDA/Datasets/StreetEasy/manhattan_details.json

# Access database
psql rentiq_db
```

### Frontend Setup
```bash
# TypeScript version
cd ts-frontend
npm install
npm run dev

# JavaScript version
cd frontend
npm install
npm start
```

---

## 📝 Notes & Decisions

### Why PostgreSQL?
- Native support for array fields (amenities, images)
- JSON field support for flexible data
- Vector extension (pgvector) for embeddings
- Robust indexing for complex queries
- AWS RDS compatibility

### Why RAG Architecture?
- Combines structured data retrieval with AI reasoning
- More accurate than pure LLM (hallucination prevention)
- Cost-effective (smaller context windows)
- Allows for cited sources and transparency

---

## 📚 Resources & References

- [Django Documentation](https://docs.djangoproject.com/)
- [PostgreSQL pgvector](https://github.com/pgvector/pgvector)
- [OpenAI Embeddings](https://platform.openai.com/docs/guides/embeddings)
- [AWS RDS Best Practices](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_BestPractices.html)
- [StreetEasy Data](https://streeteasy.com/)

---

**Last Updated**: October 15, 2025