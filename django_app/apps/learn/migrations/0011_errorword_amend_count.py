# -*- coding: utf-8 -*-
# Generated by Django 1.9 on 2017-10-19 07:45
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('learn', '0010_errorword'),
    ]

    operations = [
        migrations.AddField(
            model_name='errorword',
            name='amend_count',
            field=models.IntegerField(default=0, verbose_name='\u7ea0\u6b63\u6b21\u6570'),
        ),
    ]