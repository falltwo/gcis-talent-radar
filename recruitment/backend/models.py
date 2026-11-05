from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, UniqueConstraint, CheckConstraint, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()
def now(): return datetime.now(timezone.utc)
class Company(Base):
    __tablename__ = 'companies'
    id = Column(Integer, primary_key=True)
    company_name = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False, index=True)
    email = Column(String(254), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(20), default='hr', nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
class AccessToken(Base):
    __tablename__ = 'access_tokens'
    digest = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
class SalaryTemplate(Base):
    __tablename__ = 'salary_templates'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False, index=True)
    job_title = Column(String(100), nullable=False)
    salary_min = Column(Integer, nullable=False)
    salary_max = Column(Integer, nullable=False)
    salary_type = Column(String(20), nullable=False, default='monthly')
    currency = Column(String(3), nullable=False, default='TWD')
    data_source = Column(Text, nullable=False)
    work_location = Column(String(200), default='')
    updated_at = Column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('company_id', 'job_title'), CheckConstraint('salary_min > 0 AND salary_max >= salary_min'))
class JobTemplate(Base):
    __tablename__ = 'job_templates'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False, index=True)
    title = Column(String(100), nullable=False)
    description = Column(Text, default='')
    requirements = Column(Text, default='')
    location = Column(String(200), default='')
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    salary_type = Column(String(20), default='monthly')
    currency = Column(String(3), default='TWD')
    __table_args__ = (UniqueConstraint('company_id', 'title'),)
class RecruitmentBatch(Base):
    __tablename__ = 'recruitment_batches'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    original_text = Column(Text, nullable=False)
    status = Column(String(20), default='draft', nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
class RecruitmentBatchItem(Base):
    __tablename__ = 'recruitment_batch_items'
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey('recruitment_batches.id'), nullable=False, index=True)
    title = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    description = Column(Text, default='')
    requirements = Column(Text, default='')
    location = Column(String(200), default='')
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    salary_type = Column(String(20), default='monthly')
    currency = Column(String(3), default='TWD')
    salary_source = Column(String(30), nullable=False, default='missing')
    salary_provenance = Column(Text, default='')
    salary_confirmed = Column(Boolean, default=False, nullable=False)
    __table_args__ = (CheckConstraint('quantity > 0'),)
class JobPosting(Base):
    __tablename__ = 'job_postings'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False, index=True)
    batch_item_id = Column(Integer, ForeignKey('recruitment_batch_items.id'), unique=True, nullable=False)
    title = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    requirements = Column(Text, nullable=False)
    location = Column(String(200), nullable=False)
    salary_min = Column(Integer, nullable=False)
    salary_max = Column(Integer, nullable=False)
    salary_type = Column(String(20), nullable=False)
    currency = Column(String(3), nullable=False)
    salary_source = Column(String(30), nullable=False)
    salary_provenance = Column(Text, nullable=False)
    status = Column(String(20), default='published', nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
class ChatLog(Base):
    __tablename__ = 'chat_logs'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
class AssistantMemory(Base):
    __tablename__ = 'assistant_memories'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    conversation_id = Column(String(80), nullable=False)
    state = Column(JSON, nullable=False, default=dict)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('company_id','user_id','conversation_id'),)
class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    action = Column(String(50), nullable=False)
    entity_id = Column(Integer)
    detail = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=now)
