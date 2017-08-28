# _*_ encoding:utf-8 _*_
from __future__ import unicode_literals
from datetime import datetime

from django.db import models
from django.contrib.auth.models import AbstractUser


class UserProfile(AbstractUser):
    nick_name = models.CharField(blank=True,
                                 verbose_name=u"昵称",
                                 max_length=100)
    avatar = models.ImageField(upload_to="images/%Y/%m",
                               verbose_name=u"头像",
                               max_length=200)
    mobile_phone = models.CharField(blank=True,
                                    null=True,
                                    verbose_name=u"手机号",
                                    max_length=20)

    class Meta:
        verbose_name = u"用户信息"
        verbose_name_plural = verbose_name

    def membership_days(self):
        delta = datetime.now() - self.date_joined
        return delta.days

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return self.username


class EmailVerifyRecord(models.Model):
    code = models.CharField(max_length=20, verbose_name=u"验证码")
    email = models.EmailField(max_length=50, verbose_name=u"邮箱")
    send_type = models.CharField(verbose_name=u"验证码类型",
                                 choices=(("register", u"注册"),
                                          ("forget", u"找回密码"),
                                          ("update_email", u"修改邮箱")),
                                 max_length=30)
    send_time = models.DateTimeField(verbose_name=u"发送时间", default=datetime.now)

    class Meta:
        verbose_name = u"邮箱验证码"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return '{0}({1})'.format(self.code, self.email)


class Group(models.Model):
    name = models.CharField(blank=False, max_length=100, verbose_name=u"组名")
    description = models.CharField(blank=True, max_length=300,
                                   verbose_name=u"详细描述")
    create_time = models.DateTimeField(default=datetime.now,
                                       verbose_name=u"创建时间")
    password = models.CharField(blank=True, max_length=100,
                                verbose_name=u"进组密码")

    class Meta:
        verbose_name = u"班级"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return self.name


class UserGroup(models.Model):
    user = models.ForeignKey(UserProfile, verbose_name=u"用户")
    group = models.ForeignKey(Group, verbose_name=u"用户组")
    role = models.IntegerField(choices=((1, u"学生"), (2, u"老师")),
                               default=1,
                               verbose_name=u"组内的角色")
    join_time = models.DateField(default=datetime.now,
                                 verbose_name=u"加入时间")

    class Meta:
        verbose_name = u"学籍登记"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return "{0} - {1}".format(self.user.username, self.group.name)