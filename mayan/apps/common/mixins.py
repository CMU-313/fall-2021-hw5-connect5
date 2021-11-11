from __future__ import unicode_literals

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext
from django.views.generic.detail import SingleObjectMixin

from mayan.apps.acls.models import AccessControlList
from mayan.apps.permissions import Permission

from .forms import DynamicForm
from .literals import (
    PK_LIST_SEPARATOR, TEXT_CHOICE_ITEMS, TEXT_CHOICE_LIST,
    TEXT_LIST_AS_ITEMS_PARAMETER, TEXT_LIST_AS_ITEMS_VARIABLE_NAME
)
from .settings import setting_home_view

__all__ = (
    'DeleteExtraDataMixin', 'DynamicFormViewMixin', 'ExtraContextMixin',
    'FormExtraKwargsMixin', 'ListModeMixin', 'MultipleObjectMixin',
    'ObjectActionMixin', 'ObjectNameMixin', 'RedirectionMixin',
    'RestrictedQuerysetMixin', 'ViewPermissionCheckMixin'
)


class ContentTypeViewMixin(object):
    content_type_url_kw_args = {
        'app_label': 'app_label',
        'model': 'model'
    }

    def get_content_type(self):
        return get_object_or_404(
            klass=ContentType,
            app_label=self.kwargs[
                self.content_type_url_kw_args['app_label']
            ],
            model=self.kwargs[
                self.content_type_url_kw_args['model']
            ]
        )


class DeleteExtraDataMixin(object):
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        if hasattr(self, 'get_delete_extra_data'):
            self.object.delete(**self.get_delete_extra_data())
        else:
            self.object.delete()

        return HttpResponseRedirect(redirect_to=success_url)


class DynamicFormViewMixin(object):
    form_class = DynamicForm

    def get_form_kwargs(self):
        data = super(DynamicFormViewMixin, self).get_form_kwargs()
        data.update({'schema': self.get_form_schema()})
        return data


class ExtraContextMixin(object):
    """
    Mixin that allows views to pass extra context to the template
    """
    extra_context = {}

    def get_extra_context(self):
        return self.extra_context

    def get_context_data(self, **kwargs):
        context = super(ExtraContextMixin, self).get_context_data(**kwargs)
        context.update(self.get_extra_context())
        return context


class ExternalObjectMixin(object):
    external_object_class = None
    external_object_permission = None
    external_object_pk_url_kwarg = 'pk'
    external_object_pk_url_kwargs = None  # Usage: {'pk': 'pk'}
    external_object_queryset = None

    def dispatch(self, *args, **kwargs):
        self.external_object = self.get_external_object()
        return super(ExternalObjectMixin, self).dispatch(*args, **kwargs)

    def get_pk_url_kwargs(self):
        pk_url_kwargs = {}

        if self.external_object_pk_url_kwargs:
            pk_url_kwargs = self.external_object_pk_url_kwargs
        else:
            pk_url_kwargs['pk'] = self.external_object_pk_url_kwarg

        for key, value in pk_url_kwargs.items():
            pk_url_kwargs[key] = self.kwargs[value]

        return pk_url_kwargs

    def get_external_object(self):
        return get_object_or_404(
            klass=self.get_external_object_queryset_filtered(),
            **self.get_pk_url_kwargs()
        )

    def get_external_object_permission(self):
        return self.external_object_permission

    def get_external_object_queryset(self):
        if not self.external_object_queryset and not self.external_object_class:
            raise ImproperlyConfigured(
                'View must provide either an external_object_queryset, '
                'an external_object_class or a custom '
                'get_external_object_queryset() method.'
            )

        return self.external_object_queryset or self.external_object_class.objects.all()

    def get_external_object_queryset_filtered(self):
        queryset = self.get_external_object_queryset()
        permission = self.get_external_object_permission()

        if permission:
            queryset = AccessControlList.objects.restrict_queryset(
                permission=permission, queryset=queryset,
                user=self.request.user
            )

        return queryset


class FormExtraKwargsMixin(object):
    """
    Mixin that allows a view to pass extra keyword arguments to forms
    """
    form_extra_kwargs = {}

    def get_form_extra_kwargs(self):
        return self.form_extra_kwargs

    def get_form_kwargs(self):
        result = super(FormExtraKwargsMixin, self).get_form_kwargs()
        result.update(self.get_form_extra_kwargs())
        return result


class ListModeMixin(object):
    def get_context_data(self, **kwargs):
        context = super(ListModeMixin, self).get_context_data(**kwargs)

        if context.get(TEXT_LIST_AS_ITEMS_VARIABLE_NAME):
            default_mode = TEXT_CHOICE_ITEMS
        else:
            default_mode = TEXT_CHOICE_LIST

        list_mode = self.request.GET.get(
            TEXT_LIST_AS_ITEMS_PARAMETER, default_mode
        )

        context.update(
            {
                TEXT_LIST_AS_ITEMS_VARIABLE_NAME: list_mode == TEXT_CHOICE_ITEMS
            }
        )
        return context


class MultipleInstanceActionMixin(object):
    # TODO: Deprecated, replace views using this with
    # MultipleObjectFormActionView or MultipleObjectConfirmActionView

    model = None
    success_message_singular = _('Operation performed on %(count)d object')
    success_message_plural = _('Operation performed on %(count)d objects')

    def get_pk_list(self):
        return self.request.GET.get(
            'id_list', self.request.POST.get('id_list', '')
        ).split(',')

    def get_queryset(self):
        return self.model.objects.filter(pk__in=self.get_pk_list())

    def get_success_message(self, count):
        return ungettext(
            singular=self.success_message,
            plural=self.success_message_plural,
            number=count
        ) % {
            'count': count,
        }

    def post(self, request, *args, **kwargs):
        count = 0
        for instance in self.get_queryset():
            try:
                self.object_action(instance=instance)
            except PermissionDenied:
                pass
            else:
                count += 1

        messages.success(
            request=self.request,
            message=self.get_success_message(count=count)
        )

        return HttpResponseRedirect(redirect_to=self.get_success_url())


class MultipleObjectMixin(SingleObjectMixin):
    """
    Mixin that allows a view to work on a single or multiple objects. It can
    receive a pk, a slug or a list of IDs via an id_list query.
    The pk, slug, and ID list parameter name can be changed using the
    attributes: pk_url_kwargs, slug_url_kwarg, and pk_list_key.
    """
    pk_list_key = 'id_list'
    pk_list_separator = PK_LIST_SEPARATOR

    def dispatch(self, request, *args, **kwargs):
        self.object_list = self.get_object_list()
        if self.view_mode_single:
            self.object = self.object_list.first()

        return super(MultipleObjectMixin, self).dispatch(request=request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """
        Override BaseDetailView.get()
        """
        return super(SingleObjectMixin, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """
        Override SingleObjectMixin.get_context_data()
        """
        return super(SingleObjectMixin, self).get_context_data(**kwargs)

    def get_object(self):
        """
        Remove this method from the subclass
        """
        raise AttributeError

    def get_object_list(self, queryset=None):
        """
        Returns the list of objects the view is displaying.

        By default this requires `self.queryset` and a `pk`, `slug` ro
        `pk_list' argument in the URLconf, but subclasses can override this
        to return any object.
        """
        self.view_mode_single = False
        self.view_mode_multiple = False

        # Use a custom queryset if provided; this is required for subclasses
        # like DateDetailView
        if queryset is None:
            queryset = self.get_queryset()

        # Next, try looking up by primary key.
        pk = self.kwargs.get(self.pk_url_kwarg)
        slug = self.kwargs.get(self.slug_url_kwarg)
        pk_list = self.get_pk_list()

        if pk is not None:
            queryset = queryset.filter(pk=pk)
            self.view_mode_single = True

        # Next, try looking up by slug.
        if slug is not None and (pk is None or self.query_pk_and_slug):
            slug_field = self.get_slug_field()
            queryset = queryset.filter(**{slug_field: slug})
            self.view_mode_single = True

        if pk_list is not None:
            queryset = queryset.filter(pk__in=self.get_pk_list())
            self.view_mode_multiple = True

        # If none of those are defined, it's an error.
        if pk is None and slug is None and pk_list is None:
            raise AttributeError(
                'View %s must be called with '
                'either an object pk, a slug or an pk list.'
                % self.__class__.__name__
            )

        try:
            # Get the single item from the filtered queryset
            queryset.get()
        except queryset.model.MultipleObjectsReturned:
            # Queryset has more than one item, this is good.
            return queryset
        except queryset.model.DoesNotExist:
            raise Http404(
                _('No %(verbose_name)s found matching the query') %
                {'verbose_name': queryset.model._meta.verbose_name}
            )
        else:
            # Queryset has one item, this is good.
            return queryset

    def get_pk_list(self):
        # Accept pk_list even on POST request to allowing direct requests
        # to the view bypassing the initial GET request to submit the form.
        # Example: when the view is called from a test or a custom UI
        result = self.request.GET.get(
            self.pk_list_key, self.request.POST.get(self.pk_list_key)
        )

        if result:
            return result.split(self.pk_list_separator)
        else:
            return None


class ObjectActionMixin(object):
    """
    Mixin that performs an user action to a queryset
    """
    error_message = 'Unable to perform operation on object %(instance)s; %(exception)s.'
    post_object_action_url = None
    success_message_single = 'Operation performed on %(object)s.'
    success_message_singular = 'Operation performed on %(count)d object.'
    success_message_plural = 'Operation performed on %(count)d objects.'
    title_single = 'Perform operation on %(object)s.'
    title_singular = 'Perform operation on %(count)d object.'
    title_plural = 'Perform operation on %(count)d objects.'

    def get_context_data(self, **kwargs):
        context = super(ObjectActionMixin, self).get_context_data(**kwargs)
        title = None

        if self.view_mode_single:
            title = self.title_single % {'object': self.object}
        elif self.view_mode_multiple:
            title = ungettext(
                singular=self.title_singular,
                plural=self.title_plural,
                number=self.object_list.count()
            ) % {
                'count': self.object_list.count(),
            }

        context['title'] = title

        return context

    def get_post_object_action_url(self):
        return self.post_object_action_url

    def get_success_message(self, count):
        if self.view_mode_single:
            return self.success_message_single % {'object': self.object}

        if self.view_mode_multiple:
            return ungettext(
                singular=self.success_message_singular,
                plural=self.success_message_plural,
                number=count
            ) % {
                'count': count,
            }

    def object_action(self, instance, form=None):
        # User supplied method
        raise NotImplementedError

    def view_action(self, form=None):
        self.action_count = 0
        self.action_id_list = []

        for instance in self.object_list:
            try:
                self.object_action(form=form, instance=instance)
            except Exception as exception:
                messages.error(
                    message=self.error_message % {
                        'exception': exception, 'instance': instance
                    }, request=self.request
                )
            else:
                self.action_count += 1
                self.action_id_list.append(instance.pk)

        messages.success(
            message=self.get_success_message(count=self.action_count),
            request=self.request
        )

        # Allow get_post_object_action_url to override the redirect URL with a
        # calculated URL after all objects are processed.
        success_url = self.get_post_object_action_url()
        if success_url:
            self.success_url = success_url


class ObjectNameMixin(object):
    def get_object_name(self, context=None):
        if not context:
            context = self.get_context_data()

        object_name = context.get('object_name')

        if not object_name:
            try:
                object_name = self.object._meta.verbose_name
            except AttributeError:
                object_name = _('Object')

        return object_name


class RedirectionMixin(object):
    action_cancel_redirect = None
    next_url = None
    previous_url = None
    post_action_redirect = None

    def get_action_cancel_redirect(self):
        return self.action_cancel_redirect

    def get_context_data(self, **kwargs):
        context = super(RedirectionMixin, self).get_context_data(**kwargs)
        context.update(
            {
                'next': self.get_next_url(),
                'previous': self.get_previous_url()
            }
        )

        return context

    def get_post_action_redirect(self):
        return self.post_action_redirect

    def get_next_url(self):
        if self.next_url:
            return self.next_url
        else:
            post_action_redirect = self.get_post_action_redirect()

            return self.request.POST.get(
                'next', self.request.GET.get(
                    'next', post_action_redirect if post_action_redirect else self.request.META.get(
                        'HTTP_REFERER', reverse(setting_home_view.value)
                    )
                )
            )

    def get_previous_url(self):
        if self.previous_url:
            return self.previous_url
        else:
            action_cancel_redirect = self.get_action_cancel_redirect()

            return self.request.POST.get(
                'previous', self.request.GET.get(
                    'previous', action_cancel_redirect if action_cancel_redirect else self.request.META.get(
                        'HTTP_REFERER', reverse(setting_home_view.value)
                    )
                )
            )

    def get_success_url(self):
        return self.get_next_url() or self.get_previous_url()


class RestrictedQuerysetMixin(object):
    """
    Restrict the view's queryset against a permission via ACL checking.
    Used to restrict the object list of a multiple object view or the source
    queryset of the .get_object() method.
    """
    model = None
    object_permission = None
    source_queryset = None

    def get_source_queryset(self):
        if self.source_queryset is None:
            if self.model:
                return self.model._default_manager.all()
            else:
                raise ImproperlyConfigured(
                    "%(cls)s is missing a QuerySet. Define "
                    "%(cls)s.model, %(cls)s.source_queryset, or override "
                    "%(cls)s.get_source_queryset()." % {
                        'cls': self.__class__.__name__
                    }
                )

        return self.source_queryset.all()

    def get_queryset(self):
        queryset = self.get_source_queryset()

        if self.object_permission:
            queryset = AccessControlList.objects.restrict_queryset(
                permission=self.object_permission, queryset=queryset,
                user=self.request.user
            )

        return queryset


class ViewPermissionCheckMixin(object):
    """
    Restrict access to the view based on the user's direct permissions from
    roles. This mixing is used for views whose objects don't support ACLs or
    for views that perform actions that are not related to a specify object or
    object's permission like maintenance views.
    """
    view_permission = None

    def dispatch(self, request, *args, **kwargs):
        if self.view_permission:
            Permission.check_user_permission(
                permission=self.view_permission, user=self.request.user
            )

        return super(
            ViewPermissionCheckMixin, self
        ).dispatch(request, *args, **kwargs)
