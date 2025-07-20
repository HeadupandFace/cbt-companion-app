# forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, RadioField, SubmitField, EmailField
from wtforms.validators import DataRequired, Length, EqualTo, Email

# --- RegisterForm (UPDATED) ---
# I've added an EmailField, which is essential for Firebase Authentication.
class RegisterForm(FlaskForm):
    email = EmailField('Email Address', validators=[DataRequired(), Email()])
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=25)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    preferred_assistant = RadioField(
        'Choose Your Assistant',
        choices=[('Clara', 'Clara (Compassionate & Reflective)'), ('Alex', 'Alex (Direct & Action-Oriented)')],
        default='Clara',
        validators=[DataRequired()]
    )
    submit = SubmitField('Register')

# --- LoginForm ---
class LoginForm(FlaskForm):
    # The login form in your app uses client-side Firebase auth,
    # but having this for completeness is good practice.
    email = EmailField('Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

# --- OnboardingForm ---
class OnboardingForm(FlaskForm):
    display_name = StringField('Display Name', validators=[DataRequired(), Length(min=2, max=30)])
    submit = SubmitField('Continue')

# --- OnboardingAssessmentForm (UPDATED with gentler questions) ---
class OnboardingAssessmentForm(FlaskForm):
    primary_issues = TextAreaField(
        "What's on your mind at the moment? We're here to listen, so feel free to share a little about what brought you here today.",
        validators=[DataRequired(), Length(min=10, max=1000)],
        render_kw={"rows": 4, "placeholder": "For example: 'I've been feeling very anxious at work' or 'I'm struggling with low motivation.'"}
    )
    daily_impact = TextAreaField(
        "It can be helpful to understand how these feelings are showing up in your day-to-day life. Have you noticed any changes in areas like your work, sleep, or how you feel socially?",
        validators=[DataRequired(), Length(min=10, max=1000)],
        render_kw={"rows": 4, "placeholder": "For example: 'I've started avoiding social events' or 'I'm finding it hard to concentrate at my desk.'"}
    )
    therapy_goals = TextAreaField(
        "Looking ahead, what would a positive change look like for you? There's no right or wrong answer.",
        validators=[DataRequired(), Length(min=10, max=1000)],
        render_kw={"rows": 4, "placeholder": "For example: 'I'd like to feel more confident in meetings' or 'I want to learn how to manage my anxiety.'"}
    )
    coping_strategies = TextAreaField(
        "What have you tried so far to manage these feelings? It's okay to include things that didn't feel helpful – it's all useful information.",
        validators=[DataRequired(), Length(min=10, max=1000)],
        render_kw={"rows": 4, "placeholder": "For example: 'I try to go for a walk, but sometimes I just stay in bed.'"}
    )
    self_harm_thoughts = RadioField(
        "Finally, because your safety is our top priority, we need to ask a sensitive question. Have you had any thoughts about hurting yourself in the last couple of weeks?",
        choices=[('no', 'No'), ('yes', 'Yes')],
        validators=[DataRequired()]
    )
    submit = SubmitField('Complete Assessment')
