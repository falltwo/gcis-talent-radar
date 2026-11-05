from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Register(Strict):
    company_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$', max_length=254)
    password: str = Field(min_length=12, max_length=128)
class Login(Strict):
    email: str
    password: str = Field(max_length=128)
class Message(Strict):
    message: str = Field(min_length=1, max_length=4000)
class ExecutionRequest(Strict):
    batch_id:int=Field(gt=0)
    district:str=Field(default='',max_length=80)
class SalaryFields(Strict):
    salary_min: int | None = Field(default=None, gt=0, le=1000000000)
    salary_max: int | None = Field(default=None, gt=0, le=1000000000)
    salary_type: Literal['monthly','hourly','yearly'] = 'monthly'
    currency: Literal['TWD'] = 'TWD'
    @model_validator(mode='after')
    def salary_range(self):
        if (self.salary_min is None) != (self.salary_max is None): raise ValueError('薪資上下限須一起提供')
        if self.salary_min is not None and self.salary_max < self.salary_min: raise ValueError('薪資上限低於下限')
        return self
class TemplateIn(SalaryFields):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=10000)
    requirements: str = Field(default='', max_length=10000)
    location: str = Field(default='', max_length=200)
class ReferenceIn(SalaryFields):
    job_title: str = Field(min_length=1, max_length=100)
    salary_min: int = Field(gt=0, le=1000000000)
    salary_max: int = Field(gt=0, le=1000000000)
    data_source: str = Field(min_length=1, max_length=2000)
    work_location: str = Field(default='', max_length=200)
class ItemEdit(SalaryFields):
    title: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, le=10000)
    description: str = Field(max_length=10000)
    requirements: str = Field(max_length=10000)
    location: str = Field(max_length=200)
    confirm_salary: bool = False

class AssistantMessage(Message):
    district: str = Field(default="", max_length=80)
