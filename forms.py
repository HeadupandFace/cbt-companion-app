# forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, RadioField
from wtforms.validators import DataRequired, Email, EqualTo, Length

class RegisterForm(FlaskForm):
    """Form for users to create a new account."""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=25)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    preferred_assistant = RadioField(
        'Who would you like to talk to?',
        choices=[('Clara', 'Clara (Compassionate)'), ('Alex', 'Alex (Action-Oriented)')],
        validators=[DataRequired()],
        default='Clara'
    )
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    """Form for users to login."""
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class OnboardingForm(FlaskForm):
    """Form for the initial onboarding step to get the user's display name."""
    display_name = StringField('What would you like us to call you?', validators=[DataRequired(), Length(min=1, max=50)])
    submit = SubmitField('Continue')

class OnboardingAssessmentForm(FlaskForm):
    """A multi-step form for the user's initial assessment."""
    primary_issues = StringField('What are the main difficulties you are currently facing?', validators=[DataRequired()])
    daily_impact = StringField('How do these difficulties impact your daily life?', validators=[DataRequired()])
    therapy_goals = StringField('What do you hope to achieve from these sessions?', validators=[DataRequired()])
    coping_strategies = StringField('What coping strategies have you tried in the past?', validators=[DataRequired()])
    self_harm_thoughts = RadioField(
        'In the last two weeks, have you had any thoughts of self-harm or suicide?',
        choices=[('no', 'No'), ('yes', 'Yes')],
        validators=[DataRequired()]
    )
    submit = SubmitField('Complete Foundation Session')
